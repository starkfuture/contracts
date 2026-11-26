#!/usr/bin/env python3
"""Sign in with Google, end to end against tests/google_stub.rb (inside the pod).
    python3 tests/google.py <base-url>
Each case starts a fresh browser session at /auth/google, takes the state and nonce from the redirect
to "Google", and comes back to the callback with a code that tells the stub what to return."""
import http.cookiejar, sys, urllib.error, urllib.parse, urllib.request

BASE = sys.argv[1]
fails = []
count = 0


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class Browser:
    def __init__(self):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), NoRedirect)

    def get(self, path):
        try:
            with self.op.open(urllib.request.Request(BASE + path), timeout=30) as r:
                return r.status, r.headers.get("Location", ""), r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Location", ""), e.read().decode("utf-8", "replace")

    def start(self):
        s, loc, _ = self.get("/auth/google")
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(loc).query))
        return s, loc, q

    def back(self, scenario, q, state=None):
        code = f"{scenario}~{q.get('nonce', '')}"
        return self.get("/identity/connect/oidc-signin?" + urllib.parse.urlencode({"code": code, "state": state or q.get("state", "")}))

    def signed_in(self):
        s, loc, _ = self.get("/settings/profile")
        return s == 200


def check(name, ok, detail=""):
    global count
    count += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        fails.append(name)


s, _, page = Browser().get("/sign_in")
check("sign-in page offers Google", s == 200 and "Sign in with Google" in page, s)

b = Browser()
s, loc, q = b.start()
check("start redirects to Google with state, nonce, the company domain and the callback",
      s in (302, 303) and q.get("state") and q.get("nonce") and q.get("hd") and q.get("response_type") == "code"
      and q.get("redirect_uri", "").endswith("/identity/connect/oidc-signin"), loc)

s, loc, _ = b.back("admin", q)
check("a company account signs in as its DocuSeal user", s in (302, 303) and b.signed_in(), f"{s} {loc}")
check("that user keeps its role (admin sees users)", b.get("/settings/users")[0] == 200)

b = Browser(); _, _, q = b.start(); s, loc, _ = b.back("newuser", q)
check("a new company account gets a DocuSeal user and is signed in", b.signed_in(), f"{s} {loc}")
check("the new user is a member (no users page)", b.get("/settings/users")[0] != 200)

for scenario, why in [("archived", "an archived user"), ("otherdomain", "an account outside the company"),
                      ("nohd", "a company address on a Google account outside the company Workspace"),
                      ("hdspoof", "a company Workspace account with an outside address"),
                      ("unverified", "an unverified email"), ("wrongaud", "a token for another app"),
                      ("wrongiss", "a token from another issuer"), ("expired", "an expired token"),
                      ("forged", "a token signed with another key"), ("wrongnonce", "a token for another sign-in")]:
    b = Browser(); _, _, q = b.start(); s, loc, _ = b.back(scenario, q)
    check(f"refused: {why}", "/sign_in" in loc and not b.signed_in(), f"{s} {loc}")

b = Browser(); _, _, q = b.start(); s, loc, _ = b.back("admin", q, state="tampered")
check("refused: a callback whose state does not match the session", "/sign_in" in loc and not b.signed_in(), f"{s} {loc}")

b = Browser(); _, _, q = b.start(); b.back("newuser", q)  # signs in once, as a member
s2, loc2, _ = b.back("admin", q)  # the same state again, now claiming the admin: the state was used up
check("refused: the same callback replayed after it signed in (no switch to admin)",
      "/sign_in" in loc2 and b.get("/settings/users")[0] != 200, f"{s2} {loc2}")
s3, loc3, _ = Browser().get("/identity/connect/oidc-signin?code=admin~x&state=x")
check("refused: a callback with no sign-in started", "/sign_in" in loc3, f"{s3} {loc3}")

print(f"{count - len(fails)}/{count} Google sign-in checks passed")
sys.exit(1 if fails else 0)
