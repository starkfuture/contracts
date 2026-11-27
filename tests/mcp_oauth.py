#!/usr/bin/env python3
"""The MCP server's OAuth sign-in (Stark::McpOauthController), end to end as claude.ai does it, against
tests/google_stub.rb inside the pod. Runs after tests/matrix.py (it reuses the seeded users and contracts).
    python3 tests/mcp_oauth.py <base-url> <cast.json>
A code "as-<name>~<nonce>" makes the stub vouch for <name>@<test domain>."""
import base64, hashlib, http.cookiejar, json, re, secrets, sys, time, urllib.error, urllib.parse, urllib.request

BASE, CAST = sys.argv[1].rstrip("/"), json.load(open(sys.argv[2]))
U = CAST["users"]
CALLBACK, OTHER = "https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback"
fails, count = [], 0


def check(name, ok, detail=""):
    global count
    count += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        fails.append(name)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class Browser:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), NoRedirect)
        self.set_cookies = []

    def req(self, method, path, data=None, headers=None):
        body = data if data is None or isinstance(data, bytes) else data.encode()
        r = urllib.request.Request(BASE + path, method=method, data=body, headers=headers or {})
        try:
            with self.op.open(r, timeout=30) as resp:
                out = resp.status, resp.headers, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            out = e.code, e.headers, e.read().decode("utf-8", "replace")
        self.set_cookies += out[1].get_all("Set-Cookie") or []
        return out

    def form(self, path, fields, headers=None):
        return self.req("POST", path, urllib.parse.urlencode(fields),
                        dict({"Content-Type": "application/x-www-form-urlencoded"}, **(headers or {})))


def query(loc):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(loc).query))


def pkce():
    verifier = secrets.token_urlsafe(48)
    return verifier, base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def register(uris):
    s, _, body = Browser().req("POST", "/oauth/register", json.dumps({"client_name": "Claude", "redirect_uris": uris}),
                               {"Content-Type": "application/json"})
    return s, (json.loads(body) if body.startswith("{") else body)


def authorize_params(client, challenge, **over):
    p = {"response_type": "code", "client_id": client, "redirect_uri": CALLBACK, "code_challenge": challenge,
         "code_challenge_method": "S256", "state": "claude-state", "resource": RESOURCE}
    p.update(over)
    return {k: v for k, v in p.items() if v is not None}


def sign_in(client, who, allow=True, browser=None, **over):
    """authorize -> stub Google -> confirmation page -> consent. Returns (browser, verifier, last status, Location, page)."""
    b = browser or Browser()
    verifier, challenge = pkce()
    s, h, page = b.req("GET", "/oauth/authorize?" + urllib.parse.urlencode(authorize_params(client, challenge, **over)))
    if s not in (302, 303) or "nonce" not in query(h.get("Location", "")):
        return b, verifier, s, h.get("Location", ""), page
    g = query(h["Location"])
    s, h, page = b.req("GET", "/oauth/google/callback?" + urllib.parse.urlencode({"code": f"{who}~{g['nonce']}", "state": g["state"]}))
    key = re.search(r'name="key" value="([^"]+)"', page)
    if s != 200 or not key:
        return b, verifier, s, h.get("Location", ""), page
    s, h, page = b.form("/oauth/consent", {"key": key.group(1), **({"allow": "1"} if allow else {"deny": "1"})})
    return b, verifier, s, h.get("Location", ""), page


def token(fields):
    s, _, body = Browser().form("/oauth/token", fields)
    return s, json.loads(body) if body.startswith("{") else body


def exchange(client, code, verifier, redirect_uri=CALLBACK):
    return token({"grant_type": "authorization_code", "code": code, "client_id": client, "redirect_uri": redirect_uri,
                  "code_verifier": verifier, "resource": RESOURCE})


def connect(client, who):
    _, verifier, _, loc, _ = sign_in(client, who)
    s, body = exchange(client, query(loc).get("code", ""), verifier)
    assert s == 200, f"connect {who}: {s} {body}"
    return body


def mcp(bearer, tool=None, args=None):
    """(http status, WWW-Authenticate, 'ok'|'Forbidden'|..., data)."""
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args or {}}} if tool \
        else {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {bearer}"} if bearer else {})}
    req = urllib.request.Request(BASE + "/mcp", method="POST", data=json.dumps(msg).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            status, www, body = r.status, r.headers.get("WWW-Authenticate", ""), json.loads(r.read())
    except urllib.error.HTTPError as e:  # a CanCan denial is a 403 carrying a JSON-RPC "Forbidden"
        try:
            err = json.loads(e.read()).get("error")
        except ValueError:
            err = None
        return e.code, e.headers.get("WWW-Authenticate", ""), err.get("message") if isinstance(err, dict) else "refused", None
    if body.get("error"):
        return status, www, body["error"].get("message", "error") if isinstance(body["error"], dict) else body["error"], None
    res = body.get("result") or {}
    if not tool:
        return status, www, "ok", res
    text = res["content"][0]["text"]
    return status, www, ("error: " + text) if res.get("isError") else "ok", None if res.get("isError") else json.loads(text)


def works(access):
    return mcp(access)[0] == 200


def rejected(access):  # exactly "not authenticated", not some other failure
    s, www, _, _ = mcp(access)
    return s == 401 and "resource_metadata=" in www


class Admin:  # a web session for the admin's own settings changes
    def __init__(self):
        self.b = Browser()
        s, _, _ = self.b.req("POST", "/sign_in", json.dumps({"user": {"email": U["admin"]["email"], "password": U["admin"]["password"]}}),
                             {"Content-Type": "application/json", "Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
        assert s in (200, 201, 302), s

    def post(self, path, fields, page="/settings/mcp"):
        _, _, html = self.b.req("GET", page)
        csrf = re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)
        return self.b.form(path, dict(fields, authenticity_token=csrf), {"Referer": BASE + page})

    def mcp_switch(self, on):
        return self.post("/account_configs", {"account_config[key]": "enable_mcp", "account_config[value]": "1" if on else "0"})


# --- Discovery ----------------------------------------------------------------------------------------
s, www, outcome, _ = mcp(None)
m = re.search(r'resource_metadata="([^"]+)"', www)
check("mcp: no token -> 401 naming the resource metadata", s == 401 and m and m.group(1).endswith("/.well-known/oauth-protected-resource"), f"{s} {www}")
check("mcp: an unknown token -> 401 too", mcp("not-a-token")[0] == 401)
s, _, body = Browser().req("GET", "/.well-known/oauth-protected-resource")
prm = json.loads(body) if s == 200 else {}
RESOURCE = prm.get("resource", "")
public = urllib.parse.urlparse(m.group(1)).netloc if m else None
check("discovery: protected-resource metadata names /mcp and its authorization server on the public host",
      RESOURCE.endswith("/mcp") and urllib.parse.urlparse(RESOURCE).netloc == public and prm.get("authorization_servers"), body[:200])
check("discovery: the /mcp-suffixed metadata path answers the same", Browser().req("GET", "/.well-known/oauth-protected-resource/mcp")[2] == body)
s, _, body = Browser().req("GET", "/.well-known/oauth-authorization-server")
asm = json.loads(body) if s == 200 else {}
check("discovery: authorization-server metadata (code, S256, DCR, public clients)",
      asm.get("issuer") == prm["authorization_servers"][0] and asm.get("response_types_supported") == ["code"]
      and asm.get("code_challenge_methods_supported") == ["S256"] and asm.get("token_endpoint_auth_methods_supported") == ["none"]
      and set(asm.get("grant_types_supported", [])) == {"authorization_code", "refresh_token"}
      and all(asm.get(k, "").startswith(asm["issuer"] + "/oauth/") for k in ("authorization_endpoint", "token_endpoint", "registration_endpoint")), body[:300])

# --- Registration -----------------------------------------------------------------------------------
s, reg = register([CALLBACK, OTHER])
CLIENT = reg.get("client_id") if isinstance(reg, dict) else None
check("register: claude.ai's callbacks are accepted, as a public client", s == 201 and CLIENT and reg.get("token_endpoint_auth_method") == "none"
      and "client_secret" not in reg, f"{s} {reg}")
for uris, why in ([["https://evil.example/cb"]], "another address"), ([[CALLBACK, "https://evil.example/cb"]], "one bad address among good ones"), \
                 ([[]], "no address"), ([[CALLBACK + "/x"]], "a longer path"):
    check(f"register: refused with {why}", register(*uris)[0] == 400)

# --- Authorize: what is refused before anyone signs in -----------------------------------------------
_, challenge = pkce()
for over, why in (({"client_id": "unknown"}, "an unknown client"), ({"redirect_uri": "https://evil.example/cb"}, "an unregistered redirect")):
    s, h, _ = Browser().req("GET", "/oauth/authorize?" + urllib.parse.urlencode(authorize_params(CLIENT, challenge, **over)))
    check(f"authorize: {why} gets an error page, never a redirect", s == 400 and not h.get("Location"), f"{s} {h.get('Location')}")
for over, err, why in (({"code_challenge": None}, "invalid_request", "no PKCE"), ({"code_challenge_method": "plain"}, "invalid_request", "PKCE plain"),
                       ({"response_type": "token"}, "unsupported_response_type", "an implicit-flow request"),
                       ({"resource": "https://evil.example/mcp"}, "invalid_target", "another resource")):
    s, h, _ = Browser().req("GET", "/oauth/authorize?" + urllib.parse.urlencode(authorize_params(CLIENT, challenge, **over)))
    q = query(h.get("Location", ""))
    check(f"authorize: {why} goes back to the client with {err}", h.get("Location", "").startswith(CALLBACK) and q.get("error") == err
          and q.get("state") == "claude-state", f"{s} {h.get('Location')}")
for bad, why in (("x\x01y", "a control character"), ("y" * 256, "more than 255 characters")):
    s, h, _ = Browser().req("GET", "/oauth/authorize?" + urllib.parse.urlencode(authorize_params(CLIENT, challenge, state=bad)))
    q = query(h.get("Location", ""))
    check(f"authorize: a state with {why} goes back as invalid_request, not echoed",
          q.get("error") == "invalid_request" and "state" not in q, f"{s} {h.get('Location')}")
s, h, _ = Browser().req("GET", "/oauth/authorize?" + urllib.parse.urlencode(authorize_params(CLIENT, challenge, state="<" * 255)))
check("authorize: the longest state, all characters JSON escapes, still fits the flow cookie",
      s in (302, 303) and "nonce" in query(h.get("Location", "")), f"{s} {h.get('Location', '')[:80]}")
s, h, _ = Browser().req("POST", "/oauth/register", json.dumps({"redirect_uris": [CALLBACK]}), {"Content-Type": "application/json"})
s2, h2, _ = Browser().form("/oauth/token", {"grant_type": "refresh_token", "refresh_token": "x", "client_id": CLIENT})
check("register and token answers are never cached", "no-store" in h.get("Cache-Control", "") and "no-store" in h2.get("Cache-Control", ""),
      f"{h.get('Cache-Control')} {h2.get('Cache-Control')}")

# --- The full flow ------------------------------------------------------------------------------------
b = Browser()
verifier, challenge = pkce()
s, h, _ = b.req("GET", "/oauth/authorize?" + urllib.parse.urlencode(authorize_params(CLIENT, challenge)))
g = query(h.get("Location", ""))
check("authorize: sends the browser to Google with its own state, nonce, the company domain and the MCP callback",
      s in (302, 303) and g.get("state") and g.get("nonce") and g.get("hd") and g.get("redirect_uri", "").endswith("/oauth/google/callback")
      and g["state"] != "claude-state", h.get("Location"))
s, h, page = Browser().req("GET", "/oauth/google/callback?" + urllib.parse.urlencode({"code": f"as-m1~{g['nonce']}", "state": g["state"]}))
check("callback: another browser (no flow cookie) is refused", s == 400 and "name=\"key\"" not in page, s)
s, h, page = b.req("GET", "/oauth/google/callback?" + urllib.parse.urlencode({"code": f"as-m1~{g['nonce']}", "state": "tampered"}))
check("callback: a tampered state is refused", s == 400 and "name=\"key\"" not in page, s)

b, verifier, s, loc, _ = sign_in(CLIENT, "as-m1")
q = query(loc)
check("consent: Allow sends a code and the client's state back to claude.ai", loc.startswith(CALLBACK + "?") and q.get("code") and q.get("state") == "claude-state", f"{s} {loc}")
names = sorted(set(c.split("=", 1)[0] for c in b.set_cookies))
check("no web session is made: the only cookie is the flow's own", names == ["stark_mcp_oauth"], names)
s, body = exchange(CLIENT, q.get("code", ""), "wrong" + verifier[5:])
check("token: a wrong PKCE verifier is refused", s == 400 and body.get("error") == "invalid_grant", f"{s} {body}")
s, body = exchange(CLIENT, q.get("code", ""), verifier)
check("token: the right verifier after a wrong one is refused too (one attempt per code)", s == 400, f"{s} {body}")

_, verifier, _, loc, _ = sign_in(CLIENT, "as-m1")
s, body = exchange(CLIENT, query(loc)["code"], verifier, redirect_uri=OTHER)
check("token: a redirect_uri other than the one authorized is refused", s == 400, f"{s} {body}")

_, verifier, _, loc, page = sign_in(CLIENT, "as-m1")
code = query(loc)["code"]
s, tok = exchange(CLIENT, code, verifier)
check("token: code + verifier give a bearer access token (1 h) and a refresh token",
      s == 200 and tok.get("token_type") == "Bearer" and 3500 < tok.get("expires_in", 0) <= 3600 and tok.get("refresh_token"), f"{s} {tok}")
access = tok.get("access_token")
s, www, outcome, data = mcp(access, "search_templates", {"q": ""})
_, _, _, by_hand = mcp(U["m1"]["mcp"], "search_templates", {"q": ""})
names = sorted(t["name"] for t in data) if data else None
check("mcp: the member's OAuth token sees exactly what its own manual token sees (search_templates)",
      outcome == "ok" and names == sorted(t["name"] for t in by_hand) and "Admin private" not in names and "Company shared" in names, names)
_, _, outcome, docs = mcp(access, "search_documents", {"q": ""})
_, _, _, docs_by_hand = mcp(U["m1"]["mcp"], "search_documents", {"q": ""})
check("mcp: ... and exactly its own contracts (search_documents)", outcome == "ok" and docs and
      sorted(d["id"] for d in docs) == sorted(d["id"] for d in docs_by_hand), docs and [d["id"] for d in docs])
check("mcp: the member is refused an admin tool", mcp(access, "list_users", {})[2] == "Forbidden")
s, again = exchange(CLIENT, code, verifier)
check("token: the code used again is refused, and the tokens it gave stop working",
      s == 400 and rejected(access) and token({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "client_id": CLIENT})[0] == 400,
      f"{s} {again}")

# --- Refresh rotation ---------------------------------------------------------------------------------
t1 = connect(CLIENT, "as-m1")
s, t2 = token({"grant_type": "refresh_token", "refresh_token": t1["refresh_token"], "client_id": CLIENT})
check("refresh: gives new tokens, and the old access token stops working",
      s == 200 and t2["refresh_token"] != t1["refresh_token"] and works(t2["access_token"]) and rejected(t1["access_token"]), f"{s} {t2}")
s, _ = token({"grant_type": "refresh_token", "refresh_token": t2["refresh_token"], "client_id": "someone-else"})
check("refresh: another client's id is refused", s == 400)
s, t3 = token({"grant_type": "refresh_token", "refresh_token": t2["refresh_token"], "client_id": CLIENT})
check("refresh: rotates again", s == 200 and works(t3["access_token"]), f"{s} {t3}")
s, _ = token({"grant_type": "refresh_token", "refresh_token": t1["refresh_token"], "client_id": CLIENT})
check("refresh: a refresh token spent two rotations ago, used again, is refused and ends the connection",
      s == 400 and rejected(t3["access_token"])
      and token({"grant_type": "refresh_token", "refresh_token": t3["refresh_token"], "client_id": CLIENT})[0] == 400, s)
_, verifier, _, loc, _ = sign_in(CLIENT, "as-m1")
s, body = token({"grant_type": "authorization_code", "code": query(loc)["code"], "client_id": CLIENT, "redirect_uri": CALLBACK,
                 "code_verifier": verifier, "resource": "https://evil.example/mcp"})
check("token: another resource is refused (invalid_target)", s == 400 and body.get("error") == "invalid_target", f"{s} {body}")
s, body = exchange(CLIENT, query(loc)["code"], verifier)
check("token: ... and that attempt used the code up", s == 400 and body.get("error") == "invalid_grant", f"{s} {body}")

# --- Who may connect ----------------------------------------------------------------------------------
for who, why in (("otherdomain", "an account outside the company"), ("unverified", "an unverified email"),
                 ("hdspoof", "a company Workspace account with an outside address"), ("archived", "an archived user"),
                 ("as-off", "a user whose account has MCP off")):
    _, _, s, loc, _ = sign_in(CLIENT, who)
    check(f"refused: {why} (access_denied back to claude.ai, no code)", query(loc).get("error") == "access_denied" and "code" not in query(loc), f"{s} {loc}")
_, _, s, loc, _ = sign_in(CLIENT, "as-m1", allow=False)
check("consent: Cancel sends access_denied, no code", query(loc).get("error") == "access_denied" and "code" not in query(loc), loc)
b = Browser()
verifier, challenge = pkce()
_, h, _ = b.req("GET", "/oauth/authorize?" + urllib.parse.urlencode(authorize_params(CLIENT, challenge)))
g = query(h["Location"])
_, h, page = b.req("GET", "/oauth/google/callback?" + urllib.parse.urlencode({"code": f"as-m1~{g['nonce']}", "state": g["state"]}))
key = re.search(r'name="key" value="([^"]+)"', page).group(1)
csp = h.get("Content-Security-Policy", "")
check("consent page: its form may lead back to every Claude callback (CSP form-action), never framed or cached",
      "form-action 'self' https://claude.ai:443 https://claude.com:443" in csp and "frame-ancestors 'none'" in csp
      and "no-store" in h.get("Cache-Control", ""), csp)
s, h, _ = b.form("/oauth/consent", {"key": "wrong" + key[5:], "allow": "1"})
check("consent: the right browser with a wrong key is refused", s == 400 and "code=" not in h.get("Location", ""), f"{s} {h.get('Location')}")
s, h, _ = Browser().form("/oauth/consent", {"key": key, "allow": "1"})
check("consent: the confirmation posted from another browser is refused (CSRF)", s == 400 and "code=" not in h.get("Location", ""), f"{s} {h.get('Location')}")

# A first-time company user gets a member, as on the web.
t = connect(CLIENT, "as-oauthnew")
check("a new company user is created as a member", mcp(t["access_token"], "list_users", {})[2] == "Forbidden" and works(t["access_token"]))

# --- Changes take effect on the next call ------------------------------------------------------------
admin = Admin()
_, challenge = pkce()
s, h, _ = admin.b.req("GET", "/oauth/authorize?" + urllib.parse.urlencode(authorize_params(CLIENT, challenge)))
check("a browser already signed in to DocuSeal still goes through Google (the web session grants nothing)",
      s in (302, 303) and "nonce" in query(h.get("Location", "")) and "code" not in query(h.get("Location", "")), h.get("Location"))
m1 = connect(CLIENT, "as-m1")
o, _ = mcp(U["admin"]["mcp"], "set_user_role", {"user_id": U["m1"]["id"], "role": "admin"})[2:]
check("live: a member raised to admin gets admin tools on the same token", o == "ok" and mcp(m1["access_token"], "list_users", {})[2] == "ok", o)
mcp(U["admin"]["mcp"], "set_user_role", {"user_id": U["m1"]["id"], "role": "member"})
check("live: ... and loses them when put back to member", mcp(m1["access_token"], "list_users", {})[2] == "Forbidden")

admin.mcp_switch(False)
off = mcp(m1["access_token"])[0]
_, _, _, loc, _ = sign_in(CLIENT, "as-m1")
refused_new = query(loc).get("error") == "access_denied"
admin.mcp_switch(True)
check("live: the account's MCP switch off stops the token and refuses new connections", off == 403 and refused_new and works(m1["access_token"]), f"{off} {loc}")

tmp = connect(CLIENT, "as-oauthtemp")
uid = None
_, _, _, users = mcp(U["admin"]["mcp"], "list_users", {})
for u in users or []:
    if u.get("email") == "oauthtemp@" + U["admin"]["email"].split("@")[1]:
        uid = u["id"]
s, _, _ = admin.post(f"/users/{uid}", {"_method": "delete"}, "/settings/users")
check("live: an archived user's token stops working, and so does its refresh", uid and rejected(tmp["access_token"])
      and token({"grant_type": "refresh_token", "refresh_token": tmp["refresh_token"], "client_id": CLIENT})[0] == 400, f"{uid} {s}")

check("manual MCP tokens (Settings -> MCP) still work", works(U["m1"]["mcp"]))

# --- An unused code expires after a minute -------------------------------------------------------------
_, verifier, _, loc, _ = sign_in(CLIENT, "as-m1")
time.sleep(62)
s, body = exchange(CLIENT, query(loc)["code"], verifier)
check("token: a code older than a minute is refused", s == 400, f"{s} {body}")

print(f"{count - len(fails)}/{count} MCP OAuth checks passed")
sys.exit(1 if fails else 0)
