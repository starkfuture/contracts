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

failed = [r for r in results if not r[0]]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(len(failed))
