#!/usr/bin/env python3
"""Black-box permission matrix against a running Stark DocuSeal (API, web pages, built-in MCP).

    python3 tests/matrix.py <base-url> <cast.json>

cast.json is the CAST= line printed by tests/seed.rb. Every check states what must happen for one
role; a check that must be ALLOWED is as important as one that must be DENIED (a scoping bug that
locks everyone out would pass a deny-only suite). Exit code = number of failed checks.
"""
import http.cookiejar, json, re, sys, time, urllib.error, urllib.parse, urllib.request

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
    """Returns the tool's JSON result, or None if the call failed (HTTP error or tool error)."""
    req = urllib.request.Request(BASE + "/mcp", method="POST",
                                 data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                  "params": {"name": tool, "arguments": args}}).encode(),
                                 headers={"Authorization": f"Bearer {U[user]['mcp']}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.loads(r.read()).get("result") or {}
    except urllib.error.HTTPError:
        return None
    return None if res.get("isError") else json.loads(res["content"][0]["text"])


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

    def token(self, page_path):
        _, _, page = self.get(page_path)
        return re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)

    def form(self, method, path, fields, token_page):
        fields = dict(fields, _method=method.lower(), authenticity_token=self.token(token_page))
        return self.req("POST", path, urllib.parse.urlencode(fields),
                        {"Content-Type": "application/x-www-form-urlencoded", "Referer": BASE + token_page})

    def upload(self, path, fields, filename, content, token_page):
        boundary = "----stark" + str(len(content))
        body = b""
        for k, v in dict(fields, authenticity_token=self.token(token_page)).items():
            body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="files[]"; filename="{filename}"\r\n'
                 f'Content-Type: application/pdf\r\n\r\n').encode() + content + f"\r\n--{boundary}--\r\n".encode()
        return self.req("POST", path, body, {"Content-Type": f"multipart/form-data; boundary={boundary}",
                                             "Accept": "application/json", "Referer": BASE + token_page})


def tiny_pdf():
    """A valid one-page PDF with correct xref offsets."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


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
data = mcp("m1", "search_templates", {"q": ""})  # [{id, name}]
names = sorted(t["name"] for t in data) if data is not None else None
check("mcp: m1 search_templates sees only its own and shared", names == ["Company shared", "Member1 private"], names)
data = mcp("m2", "search_documents", {"q": ""})  # [{id, ...}] one per submission
seen = {d["id"] for d in data} if data is not None else None
check("mcp: m2 search_documents lists exactly its own contracts", seen == set(made.get("m2", [])), seen)

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
check("web: member search finds its own template and hides others'",
      s == 200 and "Member1 private" in page and "Admin private" not in page and "Manager private" not in page, f"{s}")

# Role escalation: a member editing their own user cannot make themselves admin.
s, loc, _ = web["m1"].form("PATCH", f"/users/{U['m1']['id']}", {"user[role]": "admin", "user[first_name]": "m1renamed"},
                           "/settings/profile")
s2, me = api("m1", "GET", "/templates?limit=100")
landed = api("m1", "GET", "/user")[1].get("first_name") == "m1renamed"
check("web: member editing itself keeps the edit but not a role change",
      landed and s2 == 200 and ids(me) == expect_templates["m1"], f"update {s} {loc} landed={landed}")

# Google sign-in finds people by email, so only admins may change one (Stark::UserGuard).
s, loc, _ = web["m1"].form("PATCH", "/settings/profile/update_contact", {"user[email]": "colleague@stark-test.example"},
                           "/settings/profile")
check("web: member cannot change its own email", api("m1", "GET", "/user")[1].get("email") == U["m1"]["email"], f"{s} {loc}")
s, loc, _ = web["admin"].form("PATCH", f"/users/{U['m2']['id']}", {"user[email]": "m2-new@stark-test.example", "user[role]": "member"},
                              f"/users/{U['m2']['id']}/edit")
check("web: admin can change a user's email", api("m2", "GET", "/user")[1].get("email") == "m2-new@stark-test.example", f"{s} {loc}")

# The admin's user form must keep each user's role: a form that preselects the first option would
# silently demote anyone whose user an admin edits.
_, _, edit = web["admin"].get(f"/users/{U['tm']['id']}/edit")
selected = re.findall(r'<option[^>]*selected[^>]*value="([a-z_]+)"|<option[^>]*value="([a-z_]+)"[^>]*selected', edit)
selected = [a or b for a, b in selected]
check("web: the admin's user form preselects the user's current role", selected == ["template_manager"], selected)
s, loc, _ = web["admin"].form("PATCH", f"/users/{U['tm']['id']}",
                              {"user[first_name]": "tm", "user[role]": selected[0] if selected else "member"},
                              f"/users/{U['tm']['id']}/edit")
check("web: saving the user form keeps the template manager's rights",
      ids(api("tm", "GET", "/templates?limit=100")[1]) == expect_templates["tm"], f"{s} {loc}")

# Sharing a template: members cannot publish, managers can (and it is restored after).
s, loc, _ = web["m1"].form("PATCH", f"/stark/templates/{T['t_m1']}/visibility", {"shared": "true"}, f"/templates/{T['t_m1']}")
check("web: member cannot share its own template", denied(s, loc) and ids(api("m2", "GET", "/templates")[1]) == [T["t_shared"]], f"{s} {loc}")
def tpl(tid):
    return api("admin", "GET", f"/templates/{tid}")[1]


s, loc, _ = web["tm"].form("PATCH", f"/stark/templates/{T['t_m1']}/visibility", {"shared": "true"}, f"/templates/{T['t_m1']}")
check("web: template manager shares a template, members then see it",
      s in (302, 303) and ids(api("m2", "GET", "/templates")[1]) == sorted([T["t_m1"], T["t_shared"]]), f"{s} {loc}")
web["tm"].form("PATCH", f"/stark/templates/{T['t_m1']}/visibility", {"shared": "false"}, f"/templates/{T['t_m1']}")
check("web: making it private again hides it", ids(api("m2", "GET", "/templates")[1]) == [T["t_shared"]])
s, shared = api("m1", "GET", "/templates?shared=true")
check("api: member's shared=true template list is empty", s == 200 and ids(shared) == [], f"{s} {ids(shared) if s == 200 else ''}")
s, loc, _ = web["m1"].form("POST", f"/templates/{T['t_m1']}/share_link", {"template[shared_link]": "true"}, f"/templates/{T['t_m1']}")
check("web: member cannot turn on a public signing link", denied(s, loc) and not tpl(T["t_m1"])["shared_link"], f"{s} {loc}")

# --- Publishing, copies of signed contracts, permanent delete (Stark::TemplateGuard) -------------


s, _ = api("m1", "PUT", f"/templates/{T['t_m1']}", {"shared_link": True})
check("api: member cannot turn on a public signing link on its own template", s == 403 and not tpl(T["t_m1"])["shared_link"], s)
s, _ = api("tm", "PUT", f"/templates/{T['t_m1']}", {"shared_link": True})
check("api: template manager can turn on a public signing link", s == 200 and tpl(T["t_m1"])["shared_link"], s)
api("tm", "PUT", f"/templates/{T['t_m1']}", {"shared_link": False})
# Who receives a copy of every signed contract (template preference bcc_completed): web form only
# (the API cannot set template preferences). Read back from the admin's preferences page.
def bcc_of(tid):
    s, _, page = web["admin"].get(f"/templates/{tid}/preferences")
    assert s == 200 and "csrf-token" in page, f"admin preferences page for {tid}: {s}"
    return "evil.example" in page or "archive@stark-test.example" in page, page


for user, key in (("m1", "t_m1"), ("tm", "t_shared")):
    s, loc, _ = web[user].form("POST", f"/templates/{T[key]}/preferences",
                               {"template[preferences][bcc_completed]": f"{user}@evil.example"}, f"/templates/{T[key]}")
    check(f"web: {user} cannot set a bcc for signed copies on {key}", not bcc_of(T[key])[0], f"{s} {loc}")
s, loc, _ = web["admin"].form("POST", f"/templates/{T['t_admin']}/preferences",
                              {"template[preferences][bcc_completed]": "archive@stark-test.example"}, f"/templates/{T['t_admin']}")
check("web: admin can set a bcc for signed copies", "archive@stark-test.example" in bcc_of(T["t_admin"])[1], f"{s} {loc}")
s, _ = api("tm", "DELETE", f"/templates/{T['t_m1']}?permanently=true")
check("api: template manager cannot delete a template permanently", s == 403 and api("admin", "GET", f"/templates/{T['t_m1']}")[0] == 200, s)

# --- Cloning ----------------------------------------------------------------------------------------
s, body = api("m1", "POST", f"/templates/{T['t_admin']}/clone", {"name": "stolen"})
check("api: member cannot clone a template it cannot read", s == 403, f"{s} {body}")
s, loc, _ = web["m1"].form("POST", f"/templates/{T['t_tm']}/clone", {"template[name]": "stolen"}, "/")
check("web: member cannot clone a template it cannot read", denied(s, loc), f"{s} {loc}")
api("admin", "PUT", f"/templates/{T['t_shared']}", {"shared_link": True})
s, body = api("m1", "POST", f"/templates/{T['t_shared']}/clone", {"name": "My copy"})
ok = s == 200 and isinstance(body, dict)
check("api: member can clone a shared template", ok, f"{s} {body}")
if ok:
    copy = tpl(body["id"])
    check("api: the clone is private and has no public signing link", not copy["shared_link"] and copy["author"]["id"] == U["m1"]["id"], copy.get("shared_link"))
    check("api: the clone is invisible to another member", api("m2", "GET", f"/templates/{body['id']}")[0] == 403)
api("admin", "PUT", f"/templates/{T['t_shared']}", {"shared_link": False})

# --- Documents, settings, own user ------------------------------------------------------------------
if made.get("m2"):
    check("api: member cannot download another member's documents",
          api("m1", "GET", f"/submissions/{made['m2'][0]}/documents")[0] == 403)
s, loc, _ = web["m1"].form("POST", "/account_custom_fields", {"value[][name]": "Hijacked", "value[][type]": "text"}, "/")
check("web: member cannot change the account's custom-field library", denied(s, loc), f"{s} {loc}")

check("seed: a user created without a role is a member", CAST["default_role"] == "member", CAST["default_role"])
# --- Members build their own templates on the web ----------------------------------------------------
before = set(ids(api("m1", "GET", "/templates?limit=100")[1]))
s, loc, _ = web["m1"].form("POST", "/templates", {"template[name]": "Member1 blank", "folder_name": "Default"}, "/settings/profile")
made_blank = set(ids(api("m1", "GET", "/templates?limit=100")[1])) - before
check("web: member can create a blank template, private to them",
      s in (302, 303) and "/edit" in loc and len(made_blank) == 1
      and api("m2", "GET", f"/templates/{min(made_blank)}")[0] == 403, f"{s} {loc} {made_blank}")
before = set(ids(api("m1", "GET", "/templates?limit=100")[1]))
s, loc, body = web["m1"].upload("/templates_upload", {"folder_name": "Default"}, "upload.pdf", tiny_pdf(), "/settings/profile")
made_upload = set(ids(api("m1", "GET", "/templates?limit=100")[1])) - before
check("web: member can create a template from a PDF", len(made_upload) == 1, f"{s} {loc} {body[:120]}")

# --- MCP writes -----------------------------------------------------------------------------------
signer = [{"email": "mcp-signer@example.com", "role": "Signer"}]
check("mcp: member cannot send from a template it cannot read",
      mcp("m1", "send_documents", {"template_id": T["t_admin"], "submitters": signer}) is None)
check("mcp: member can send from a shared template",
      mcp("m1", "send_documents", {"template_id": T["t_shared"], "submitters": signer}) is not None)

# --- Admin keeps the destructive powers the guard takes from others ---------------------------------
victim = next(iter(made_blank), None)
if victim:
    s, _ = api("admin", "DELETE", f"/templates/{victim}?permanently=true")
    check("api: admin can delete a template permanently", s == 200 and api("admin", "GET", f"/templates/{victim}")[0] == 404, s)

# --- A contract's own BCC (read back by tests/probe.rb in the pod) ------------------------------------
for user, bcc in (("m1", "m1-bcc@evil.example"), ("admin", "archive-sub@stark-test.example")):
    s, _ = api(user, "POST", "/submissions", {"template_id": T["t_shared"], "send_email": False, "bcc_completed": bcc,
                                              "submitters": [{"role": "Signer", "email": f"{user}-bcc@example.com"}]})
    check(f"api: {user} can send with a bcc field", s == 200, s)

# --- Stark MCP tools -------------------------------------------------------------------------------
# Each tool must ask CanCan what the web/API asks: allowed for whoever may, Forbidden or Not found for
# everyone else, and never anything of another sender's contract.
def mcpx(who, tool, args):
    """('ok', data) | ('Forbidden', None) | ('Not found', None) | ('error: <text>', None) | ('refused: ...', None)"""
    token = U[who]["mcp"] if who in U else who
    req = urllib.request.Request(BASE + "/mcp", method="POST",
                                 data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                  "params": {"name": tool, "arguments": args}}).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            body = json.loads(raw)
        except ValueError:
            return f"http {e.code}", None
    if isinstance(body.get("error"), str):
        return "refused: " + body["error"], None
    if body.get("error"):
        return ("Forbidden" if body["error"].get("message") == "Forbidden" else f"rpc {body['error']}"), None
    res = body.get("result") or {}
    text = res["content"][0]["text"]
    if res.get("isError"):
        return ("Not found" if text == "Not found" else "error: " + text), None
    return "ok", json.loads(text)


def events(sub_id):
    s, body = api("admin", "GET", f"/submissions/{sub_id}")
    return [e["event_type"] for e in body.get("submission_events", [])] if s == 200 else None


def wait_event(sub_id, kind, seconds=40):
    for _ in range(seconds):
        if kind in (events(sub_id) or []):
            return True
        time.sleep(1)
    return False


def no_email(sub_id):  # the events were read (a failed read is not "no email") and none is a send
    ev = events(sub_id)
    return ev is not None and "send_email" not in ev


def denied_mcp(outcome):
    return outcome in ("Forbidden", "Not found")


tools_req = urllib.request.Request(BASE + "/mcp", method="POST", headers={"Authorization": f"Bearer {U['m1']['mcp']}",
                                   "Content-Type": "application/json"},
                                   data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode())
listed = {t["name"]: t for t in json.loads(urllib.request.urlopen(tools_req, timeout=30).read())["result"]["tools"]}
want_tools = {"search_templates", "load_template", "create_template", "send_documents", "search_documents",
              "get_document", "archive_document", "resend_invitation", "share_template", "list_users",
              "set_user_role", "invite_user"}
check("mcp: tools/list has every tool, each with a schema and annotations",
      set(listed) == want_tools and all(t.get("inputSchema") and "readOnlyHint" in t.get("annotations", {}) for t in listed.values()),
      sorted(listed))
check("mcp: send_documents offers no bcc", "bcc" not in json.dumps(listed.get("send_documents", {})))

# send_documents: send_email false returns links and sends nothing; readonly false; order; message.
o, nomail = mcpx("m1", "send_documents", {
    "template_id": T["t_shared"], "send_email": False, "order": "preserved", "bcc_completed": "mcp-bcc@evil.example",
    "message": {"subject": "Please sign", "body": "Hello {{submitter.link}}"},
    "submitters": [{"email": "nomail-signer@example.com", "role": "Signer", "bcc_completed": "mcp-signer-bcc@evil.example",
                    "fields": [{"name": "Name", "value": "Editable prefill", "readonly": False}]}]})
links = (nomail or {}).get("submitters") or []
check("mcp: send_documents with send_email false returns each signer's signing URL",
      o == "ok" and len(links) == 1 and "/s/" in links[0].get("signing_url", ""), f"{o} {nomail}")
o, mailed = mcpx("m1", "send_documents", {"template_id": T["t_shared"], "submitters": [
    {"email": "mailed-signer@example.com", "role": "Signer", "fields": [{"name": "Name", "value": "Locked prefill"}]}]})
check("mcp: send_documents by default emails and returns no links", o == "ok" and "submitters" not in mailed, f"{o} {mailed}")
nomail_id, mailed_id = (nomail or {}).get("id"), (mailed or {}).get("id")
nomail_sid = links[0]["id"] if links else None


def field(sub_id, name):
    s, body = api("m1", "GET", f"/submissions/{sub_id}?include=fields")
    if s != 200:
        return {}, {}
    return next((f for f in body.get("fields") or [] if f.get("name") == name), {}), body


f, body = field(nomail_id, "Name")
check("mcp: readonly false leaves the prefilled field editable", f.get("readonly") is False and f.get("default_value") == "Editable prefill", f)
api_signers = {x["id"]: x["slug"] for x in body.get("submitters") or []}
check("mcp: the returned links are this contract's own signers",
      bool(links) and all(api_signers.get(l["id"]) and l["signing_url"].endswith("/s/" + api_signers[l["id"]]) for l in links),
      f"{links} {api_signers}")
check("mcp: order preserved is kept",body.get("submitters_order") == "preserved", body.get("submitters_order"))
check("mcp: a custom message is attached to the signer",
      bool(((body.get("submitters") or [{}])[0].get("preferences") or {}).get("email_message_uuid")), body.get("submitters"))
f, _ = field(mailed_id, "Name")
check("mcp: prefilled fields stay readonly by default", f.get("readonly") is True and f.get("default_value") == "Locked prefill", f)
check("mcp: the default send emails the signer", wait_event(mailed_id, "send_email"), events(mailed_id))
check("mcp: send_email false sent no email (while the default one did)", no_email(nomail_id), events(nomail_id))

# get_document: the sender and admins only.
for who, want in (("m1", "ok"), ("admin", "ok"), ("m2", "Not found"), ("tm", "Not found")):
    o, doc = mcpx(who, "get_document", {"submission_id": nomail_id})
    good = o == want and (want != "ok" or (doc["status"] == "pending" and doc["template_name"] == "Company shared"
                                           and doc["submitters"][0]["role"] == "Signer"
                                           and doc["submitters"][0]["signing_url"].endswith("/s/" + api_signers.get(nomail_sid, "?"))
                                           and doc["documents"] == []))
    check(f"mcp: {who} get_document on m1's contract -> {want}", good, f"{o} {doc}")
o, _ = mcpx("m1", "get_document", {"submission_id": made["m2"][0]}) if made.get("m2") else ("skip", None)
check("mcp: m1 get_document on m2's contract -> Not found", o == "Not found", o)

# resend_invitation: the sender (and admins); nobody else.
for who in ("m2", "tm"):
    o, _ = mcpx(who, "resend_invitation", {"submitter_id": nomail_sid})
    check(f"mcp: {who} cannot resend m1's invitation", denied_mcp(o), o)
check("mcp: a refused resend sent nothing", no_email(nomail_id)
      and api("m1", "GET", f"/submitters/{nomail_sid}")[1].get("sent_at") is None, events(nomail_id))
o, res = mcpx("m1", "resend_invitation", {"submitter_id": nomail_sid})
check("mcp: m1 resends its own invitation and the email goes out", o == "ok" and wait_event(nomail_id, "send_email"), f"{o} {res}")
if made.get("m2"):
    m2_sid = api("admin", "GET", f"/submissions/{made['m2'][0]}")[1]["submitters"][0]["id"]
    o, _ = mcpx("admin", "resend_invitation", {"submitter_id": m2_sid})
    check("mcp: admin can resend any invitation", o == "ok", o)
    o, _ = mcpx("m1", "resend_invitation", {"submitter_id": m2_sid})
    check("mcp: m1 cannot resend m2's invitation", denied_mcp(o), o)

# Signed: documents and audit log as download URLs, still for the sender only.
s, _ = api("m1", "PUT", f"/submitters/{nomail_sid}", {"completed": True})
o, doc = mcpx("m1", "get_document", {"submission_id": nomail_id})
pdf_ok = False
if o == "ok" and doc.get("documents"):
    with urllib.request.urlopen(doc["documents"][0]["url"].replace("http://localhost:3000", BASE), timeout=30) as r:
        pdf_ok = r.read(5) == b"%PDF-"
check("mcp: a completed document returns the signed PDF and the audit log",
      o == "ok" and doc["status"] == "completed" and pdf_ok and bool(doc.get("audit_log_url"))
      and doc["submitters"][0]["status"] == "completed", f"complete {s} {o} {doc}")
o, _ = mcpx("m2", "get_document", {"submission_id": nomail_id})
check("mcp: m2 cannot get m1's signed document", o == "Not found", o)
o, _ = mcpx("m1", "resend_invitation", {"submitter_id": nomail_sid})
check("mcp: resending to a signer who completed is refused", o.startswith("error:"), o)

# archive_document: as the web/API archive (whoever may destroy the contract).
for who in ("m2", "tm"):
    o, _ = mcpx(who, "archive_document", {"submission_id": mailed_id})
    check(f"mcp: {who} cannot archive m1's contract",
          denied_mcp(o) and not api("m1", "GET", f"/submissions/{mailed_id}")[1].get("archived_at"), o)
o, _ = mcpx("m1", "archive_document", {"submission_id": mailed_id})
check("mcp: m1 archives its own contract", o == "ok" and bool(api("m1", "GET", f"/submissions/{mailed_id}")[1].get("archived_at")), o)
if made.get("m2"):
    o, _ = mcpx("admin", "archive_document", {"submission_id": made["m2"][0]})
    check("mcp: admin can archive any contract", o == "ok", o)

# share_template: template managers and admins; members never, not even their own template.
o, _ = mcpx("m1", "share_template", {"template_id": T["t_m1"], "shared": True})
check("mcp: member cannot share its own template", o == "Forbidden" and T["t_m1"] not in ids(api("m2", "GET", "/templates")[1]), o)
o, _ = mcpx("m2", "share_template", {"template_id": T["t_shared"], "shared": False})
check("mcp: member cannot make the company template private",
      o == "Forbidden" and T["t_shared"] in ids(api("m2", "GET", "/templates")[1]), o)
o, _ = mcpx("m1", "share_template", {"template_id": T["t_admin"], "shared": True})
check("mcp: member cannot share a template it cannot see", o == "Not found", o)
o, _ = mcpx("tm", "share_template", {"template_id": T["t_m1"], "shared": True})
check("mcp: template manager shares a template, members then see it",
      o == "ok" and T["t_m1"] in ids(api("m2", "GET", "/templates")[1]), o)
o, _ = mcpx("admin", "share_template", {"template_id": T["t_m1"], "shared": False})
check("mcp: admin makes it private again", o == "ok" and T["t_m1"] not in ids(api("m2", "GET", "/templates")[1]), o)

# Users: admin only.
for who in ("m1", "tm"):
    for tool, args in (("list_users", {}), ("set_user_role", {"user_id": U["m2"]["id"], "role": "admin"}),
                       ("set_user_role", {"user_id": U[who]["id"], "role": "admin"}),
                       ("set_user_role", {"user_id": 999999, "role": "admin"}),
                       ("invite_user", {"email": f"by-{who}@stark-test.example", "first_name": "x", "last_name": "y"})):
        o, _ = mcpx(who, tool, args)
        on_self = {U[who]["id"]: " on itself", 999999: " on a missing user"}.get(args.get("user_id"), "")
        check(f"mcp: {who} {tool}{on_self} -> Forbidden", o == "Forbidden", o)
check("mcp: refused role changes changed nothing",
      all(api(who, "GET", f"/templates/{T['t_admin']}")[0] == 403 for who in ("m1", "m2"))
      and api("tm", "GET", f"/submissions/{made['m1'][0]}")[0] == 403)
o, users = mcpx("admin", "list_users", {})
roles = {u["email"]: u["role"] for u in users or []}
check("mcp: admin lists users with their roles", o == "ok" and roles.get(U["tm"]["email"]) == "template_manager"
      and roles.get(U["m1"]["email"]) == "member" and roles.get(U["admin"]["email"]) == "admin"
      and "by-m1@stark-test.example" not in roles, f"{o} {roles}")
o, _ = mcpx("admin", "set_user_role", {"user_id": CAST["mcp_off_user"], "role": "member"})
check("mcp: admin cannot change a user of another account", o == "Not found", o)
o, _ = mcpx("admin", "set_user_role", {"user_id": U["admin"]["id"], "role": "member"})
check("mcp: admin cannot change its own role", o == "Forbidden", o)
o, _ = mcpx("admin", "set_user_role", {"user_id": U["m2"]["id"], "role": "owner"})
check("mcp: an unknown role is refused", o.startswith("error:"), o)
o, _ = mcpx("admin", "set_user_role", {"user_id": U["m2"]["id"], "role": "template_manager"})
check("mcp: admin makes m2 a template manager, and m2 then sees every template",
      o == "ok" and ids(api("m2", "GET", "/templates?limit=100")[1]) == ids(api("tm", "GET", "/templates?limit=100")[1]), o)
o, _ = mcpx("admin", "set_user_role", {"user_id": U["m2"]["id"], "role": "member"})
check("mcp: and back to member", o == "ok" and ids(api("m2", "GET", "/templates?limit=100")[1]) == [T["t_shared"]], o)
o, inv = mcpx("admin", "invite_user", {"email": "Invited@stark-test.example", "first_name": "In", "last_name": "Vited"})
check("mcp: admin invites a user, a member by default",
      o == "ok" and inv["role"] == "member" and inv["email"] == "invited@stark-test.example", f"{o} {inv}")
o, _ = mcpx("admin", "invite_user", {"email": "invited@stark-test.example", "first_name": "In", "last_name": "Vited"})
check("mcp: inviting an existing user is refused", o.startswith("error:"), o)
o, _ = mcpx("admin", "invite_user", {"email": "bogus-role@stark-test.example", "first_name": "b", "last_name": "r", "role": "owner"})
check("mcp: inviting with an unknown role is refused (upstream would make an admin)",
      o.startswith("error:") and "bogus-role@stark-test.example" not in {u["email"] for u in mcpx("admin", "list_users", {})[1] or []}, o)

# An account with MCP off is refused, whatever the tool.
for tool in ("get_document", "list_users"):
    o, _ = mcpx(CAST["mcp_off"], tool, {"submission_id": nomail_id})
    check(f"mcp: account with MCP disabled is refused ({tool})", o == "refused: MCP is disabled", o)

failed = [r for r in results if not r[0]]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(len(failed))
