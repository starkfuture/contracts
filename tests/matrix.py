#!/usr/bin/env python3
"""Black-box permission matrix against a running Stark DocuSeal (API, web pages, built-in MCP).

    python3 tests/matrix.py <base-url> <cast.json>

cast.json is the CAST= line printed by tests/seed.rb. Every check states what must happen for one
role; a check that must be ALLOWED is as important as one that must be DENIED (a scoping bug that
locks everyone out would pass a deny-only suite). Exit code = number of failed checks.
"""
import http.cookiejar, json, re, sys, urllib.error, urllib.parse, urllib.request

BASE, CAST = sys.argv[1].rstrip("/"), json.load(open(sys.argv[2]))
U, T = CAST["users"], CAST["templates"]
results = []


def check(name, ok, detail=""):
    results.append((ok, name, detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def api(user, method, path, body=None):
    req = urllib.request.Request(BASE + "/api" + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Auth-Token": U[user]["token"], "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw[:200]


def mcp(user, tool, args):
    req = urllib.request.Request(BASE + "/mcp", method="POST",
                                 data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                  "params": {"name": tool, "arguments": args}}).encode(),
                                 headers={"Authorization": f"Bearer {U[user]['mcp']}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.loads(r.read())["result"]
    return res, json.loads(res["content"][0]["text"]) if not res.get("isError") else None


class Web:
    def __init__(self, user):
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), NoRedirect)
        s, _, _ = self.req("POST", "/sign_in", json.dumps({"user": {"email": U[user]["email"], "password": U[user]["password"]}}),
                           {"Content-Type": "application/json", "Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
        assert s in (200, 201, 302), f"sign in {user}: {s}"

    def req(self, method, path, data=None, headers=None):
        r = urllib.request.Request(BASE + path, method=method, data=data.encode() if isinstance(data, str) else data,
                                   headers=headers or {})
        try:
            with self.op.open(r, timeout=30) as resp:
                return resp.status, resp.headers.get("Location", ""), resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Location", ""), e.read().decode("utf-8", "replace")

    def get(self, path):
        return self.req("GET", path)

    def form(self, method, path, fields, token_page):
        _, _, page = self.get(token_page)
        token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
        fields = dict(fields, _method=method.lower(), authenticity_token=token)
        return self.req("POST", path, urllib.parse.urlencode(fields), {"Content-Type": "application/x-www-form-urlencoded"})


def denied(status, location):  # DocuSeal web answers a denied page with a redirect to root
    return status in (302, 303) and urllib.parse.urlparse(location).path in ("", "/")


def ids(payload):
    return sorted(x["id"] for x in payload["data"])


# --- Templates over the API -------------------------------------------------------------------
everything = sorted(T.values())
expect_templates = {"admin": everything, "tm": everything, "m1": sorted([T["t_m1"], T["t_shared"]]),
                    "m2": [T["t_shared"]]}
for user, want in expect_templates.items():
    s, body = api(user, "GET", "/templates?limit=100")
    check(f"api: {user} lists exactly its templates", s == 200 and ids(body) == want, f"{s} {body if s != 200 else ids(body)}")

check("api: m1 cannot open admin's private template", api("m1", "GET", f"/templates/{T['t_admin']}")[0] == 403)
check("api: m2 cannot open m1's private template", api("m2", "GET", f"/templates/{T['t_m1']}")[0] == 403)
check("api: m1 can open the shared template", api("m1", "GET", f"/templates/{T['t_shared']}")[0] == 200)
check("api: tm can open m1's private template", api("tm", "GET", f"/templates/{T['t_m1']}")[0] == 200)
check("api: m1 cannot rename the shared template", api("m1", "PUT", f"/templates/{T['t_shared']}", {"name": "x"})[0] == 403)
check("api: m2 cannot archive m1's template", api("m2", "DELETE", f"/templates/{T['t_m1']}")[0] == 403)
s, _ = api("m1", "PUT", f"/templates/{T['t_m1']}", {"name": "Member1 private"})
check("api: m1 can edit its own template", s == 200, s)
s, _ = api("tm", "PUT", f"/templates/{T['t_shared']}", {"name": "Company shared"})
check("api: tm can edit any template", s == 200, s)

# --- Contracts over the API ---------------------------------------------------------------------
def send(user, template):
    return api(user, "POST", "/submissions", {"template_id": T[template], "send_email": False,
                                              "submitters": [{"role": "Signer", "email": f"{user}-signer@example.com"}]})


made = {}
for user, template in (("m1", "t_shared"), ("m2", "t_shared"), ("admin", "t_admin"), ("tm", "t_tm"), ("m1", "t_m1")):
    s, body = send(user, template)
    ok = s == 200 and isinstance(body, list) and body
    check(f"api: {user} can send from {template}", ok, f"{s} {body}")
    if ok:
        made.setdefault(user, []).append(body[0]["submission_id"])
for user, template in (("m1", "t_admin"), ("m2", "t_m1"), ("m1", "t_tm")):
    s, body = send(user, template)
    check(f"api: {user} cannot send from {template}", s == 403, f"{s} {body}")

allsubs = sorted(x for v in made.values() for x in v)
for user in U:
    s, body = api(user, "GET", "/submissions?limit=100")
    want = allsubs if user == "admin" else sorted(made.get(user, []))
    check(f"api: {user} lists exactly its contracts", s == 200 and ids(body) == want, f"{s} {ids(body) if s == 200 else body}")
if made.get("m2") and made.get("m1"):
    check("api: m1 cannot open m2's contract", api("m1", "GET", f"/submissions/{made['m2'][0]}")[0] == 403)
    check("api: tm cannot open m1's contract", api("tm", "GET", f"/submissions/{made['m1'][0]}")[0] == 403)
    check("api: admin can open m1's contract", api("admin", "GET", f"/submissions/{made['m1'][0]}")[0] == 200)
    check("api: m2 cannot archive m1's contract", api("m2", "DELETE", f"/submissions/{made['m1'][0]}")[0] == 403)
    s, body = api("m1", "GET", "/submitters?limit=100")
    mine = {x["submission_id"] for x in body["data"]} if s == 200 else None
    check("api: m1 lists only its own signers", s == 200 and mine == set(made["m1"]), f"{s} {mine}")
    s, body = api("m1", "GET", f"/submitters?template_id={T['t_shared']}")
    mine = {x["submission_id"] for x in body["data"]} if s == 200 else None
    check("api: m1 filtering signers by the shared template sees only its own", s == 200 and mine == {made["m1"][0]}, f"{s} {mine}")

# --- Built-in MCP -------------------------------------------------------------------------------
res, data = mcp("m1", "search_templates", {"q": ""})
names = sorted(x.get("name") for x in (data if isinstance(data, list) else (data or {}).get("templates", data or [])) or []) if data is not None else res
check("mcp: m1 search_templates sees only its own and shared", names == ["Company shared", "Member1 private"], names)
res, data = mcp("m2", "search_documents", {"q": ""})
text = json.dumps(data)
check("mcp: m2 search_documents does not include m1's contracts",
      data is not None and all(f'"id": {i}' not in text and f'"id":{i}' not in text for i in made.get("m1", [])), text[:200])

# --- Web pages and settings ---------------------------------------------------------------------
web = {u: Web(u) for u in U}
for path in ("/settings/users", "/settings/webhooks", "/settings/personalization", "/settings/email",
             "/settings/account", "/settings/notifications", "/settings/storage"):
    s, loc, _ = web["m1"].get(path)
    check(f"web: member denied {path}", denied(s, loc), f"{s} {loc}")
    s, loc, _ = web["admin"].get(path)
    check(f"web: admin allowed {path}", s == 200, f"{s} {loc}")
for path in ("/settings/profile", "/settings/api"):
    s, loc, _ = web["m1"].get(path)
    check(f"web: member allowed {path}", s == 200, f"{s} {loc}")
s, loc, _ = web["m1"].get(f"/templates/{T['t_admin']}")
check("web: member cannot open another's private template page", denied(s, loc), f"{s} {loc}")
s, loc, page = web["m1"].get("/")
check("web: member dashboard lists own + shared templates only",
      s == 200 and "Member1 private" in page and "Company shared" in page and "Admin private" not in page and "Manager private" not in page,
      f"{s} {loc}")
s, loc, page = web["m1"].get("/search?q=private")
check("web: member search hides others' templates", s == 200 and "Admin private" not in page and "Manager private" not in page, f"{s}")

# Role escalation: a member editing their own user cannot make themselves admin.
s, loc, _ = web["m1"].form("PATCH", f"/users/{U['m1']['id']}", {"user[role]": "admin", "user[first_name]": "m1"},
                           "/settings/profile")
s2, me = api("m1", "GET", "/templates?limit=100")
check("web: member cannot promote itself to admin", s2 == 200 and ids(me) == expect_templates["m1"], f"update {s} {loc}")

# Sharing a template: members cannot publish, managers can (and it is restored after).
s, loc, _ = web["m1"].form("PATCH", f"/stark/templates/{T['t_m1']}/visibility", {"shared": "true"}, f"/templates/{T['t_m1']}")
check("web: member cannot share its own template", denied(s, loc) and ids(api("m2", "GET", "/templates")[1]) == [T["t_shared"]], f"{s} {loc}")
s, loc, _ = web["tm"].form("PATCH", f"/stark/templates/{T['t_m1']}/visibility", {"shared": "true"}, f"/templates/{T['t_m1']}")
check("web: template manager shares a template, members then see it",
      s in (302, 303) and ids(api("m2", "GET", "/templates")[1]) == sorted([T["t_m1"], T["t_shared"]]), f"{s} {loc}")
web["tm"].form("PATCH", f"/stark/templates/{T['t_m1']}/visibility", {"shared": "false"}, f"/templates/{T['t_m1']}")
check("web: making it private again hides it", ids(api("m2", "GET", "/templates")[1]) == [T["t_shared"]])
s, loc, _ = web["m1"].form("POST", f"/templates/{T['t_m1']}/share_link", {"template[shared_link]": "true"}, f"/templates/{T['t_m1']}")
check("web: member cannot turn on a public signing link", denied(s, loc), f"{s} {loc}")

check("seed: a user created without a role is a member", CAST["default_role"] == "member", CAST["default_role"])

failed = [r for r in results if not r[0]]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(len(failed))
