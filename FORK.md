# Stark DocuSeal: what this fork changes and why

DocuSeal Community edition gives every user full admin rights over every template, contract and
setting. Stark contracts can be confidential, so this fork adds roles. Everything else is upstream
DocuSeal, unchanged.

## Intent

- **member** (default for new users): sees and sends only the contracts they sent; sees their own
  templates and the templates shared with the company; edits only their own templates; no settings.
- **template_manager**: sees, creates, edits and shares every template. Contracts: only their own.
- **admin**: everything, as upstream: every contract, every template, users and all settings.
- Templates are private to their author until a template_manager or admin shares them.
- Seeing a template never grants seeing other people's contracts made from it.
- Publishing (sharing a template with the company, or turning on a public signing link) needs
  template_manager or admin. A clone starts private and without a public link.
- Only admins decide who receives a copy of every signed contract (a template's BCC, or a
  contract's own BCC at send time), delete a template permanently (it destroys every contract made
  from it), or change account settings, including the template builder's custom-field library.
- Only admins assign roles and change a user's email. The first user created at setup is admin. Existing users keep the role
  they had: after the first deploy every pre-existing user is still admin until an admin changes it.
- The built-in MCP server (`/mcp`, per-user tokens) follows the same rules: it asks the same
  permission class.
- Through the MCP server people do what they already may do on the web, nothing more: follow their
  own contracts to the signed copy, archive them, resend a signer's invitation, send without email
  and hand the signing links over themselves, choose signing order and the invitation text, and leave
  a prefilled value editable (locked stays the default). Template managers and admins share
  templates; admins list users, invite them and change roles. Nobody changes their own role, so the
  last admin stays one. Nobody but an admin sets who gets a copy of a signed contract, so the send
  tool offers no BCC.
- People sign in with their company Google account. A company address with no DocuSeal user yet gets
  one as a member; an admin raises the role. Archived users stay out. Accounts outside the company
  domain are refused, even inside a company Google Workspace. Password sign-in keeps working
  (first setup, break-glass).
- Adding the MCP server to Claude (claude.ai custom connector) needs no token: Claude sends the person
  to company Google, they confirm once, and Claude then acts as exactly their DocuSeal user. Who may
  connect follows the Google sign-in rules above. The connection follows the person's role, archiving
  and the account's MCP switch on every call, so a change applies at once. It lasts at most 30 days,
  then the person signs in with Google again. Hand-made tokens (Settings -> MCP) keep working.
- Whoever leaves the company is archived in DocuSeal: that ends their Claude connection at once.
  Losing the Google account only stops new connections; an existing one runs to its 30-day end.

## How the fork is built

Upstream source is not copied here. The image is the official DocuSeal image (the multi-arch index
mirrored in ECR, pinned by digest in `UPSTREAM` and passed to the `Dockerfile` as `BASE`) plus
`build/app/`, which `tools/assemble.py` makes from:

- `PINS`: sha256 of the full upstream content of every file we patch, plus the permission rules
  Stark replaces for non-admins (`lib/ability.rb`, `lib/abilities/template_conditions.rb`), and
  the upstream behaviour the rules rely on unpatched: users editing themselves cannot change their
  role (`users_controller.rb`), BCC precedence (`process_submitter_completion_job.rb`), the
  template preferences form (`templates_preferences_controller.rb`), the contract model
  (`submission.rb`: preferences stored as JSON with string keys, which the BCC guard relies on), and
  what the Stark MCP tools mirror: the MCP base controller (token, MCP switch, Forbidden), the web resend
  and the API's contract show and archive. Any
  upstream change in them stops the build for a human re-read. Because every patched file is
  pinned whole, a patch can only fail after its pin already has; the pin is the tripwire.
  The test pod also checks the image's own copies against PINS, so the image provably holds the
  same upstream source the patches were made against.
- `patches/`: small edits to upstream files.
- `overlay/`: Stark's own files.

The Dockerfile is a single COPY, so nothing runs at build time and both architectures build the same.

| Patch | Upstream file | Why |
|---|---|---|
| 0001 | `lib/ability.rb` | Non-admins get the Stark rules; admins also get `:share`. |
| 0002 | `app/models/user.rb` | Adds the roles; new users default to member. |
| 0003 | `app/controllers/setup_controller.rb` | The first user is admin. |
| 0004 | `app/views/users/_role_select.html.erb` | The Stark roles, with the user's current role selected; no Pro upsell. |
| 0005 | `app/views/templates/_access_icon.html.erb` | Private/Shared badge and share button (empty upstream). |
| 0006 | `lib/templates/clone.rb` | A clone starts without a public signing link. |
| 0007 | `app/views/shared/_powered_by.html.erb` | "Source" link next to the DocuSeal credit (licence). |
| 0008 | `app/controllers/account_custom_fields_controller.rb` | The custom-field library is admin-only. |
| 0009 | `app/models/template.rb` | Template lists load `stark_shared`, which the rules read. |
| 0010 | `lib/templates.rb` | Templates shared from linked accounts (web list and API `shared=true`) are admin-only: they bypass the Stark rules. |
| 0011 | `app/views/devise/sessions/_omniauthable.html.erb` | "Sign in with Google" on the sign-in page (empty upstream). |
| 0012 | `app/controllers/mcp_controller.rb` | Registers the Stark MCP tools. |
| 0013 | `app/controllers/mcp/send_documents_controller.rb` | Send without email (returns the signing links), signing order, invitation text, editable prefill. |
| 0014 | `app/controllers/mcp/mcp_base_controller.rb` | The MCP server also accepts tokens from the Claude sign-in, and its 401 says where to sign in. |

| Stark file | What |
|---|---|
| `lib/stark/ability.rb` | The rules for member and template_manager. |
| `lib/stark/template_guard.rb` | Publishing, a template's BCC and permanent delete, enforced on the model so every path (web, API, MCP, clone) is covered. |
| `lib/stark/user_guard.rb` | Only admins change a user's email (Google sign-in links people by email). |
| `lib/stark/submission_guard.rb` | A contract's own BCC set or changed by anyone but an admin is put back; other saves (signing) leave it alone. |
| `config/locales/stark.en.yml` | Role names in the users list. |
| `lib/stark.rb` | The source URL for the "Source" link. |
| `lib/stark/google.rb`, `app/controllers/stark/google_sessions_controller.rb`, `app/views/stark/_google_sign_in.html.erb` | Sign in with Google (OpenID Connect code flow, ID token signature checked against Google's keys with the `jwt` gem DocuSeal already ships). |
| `app/views/layouts/mailer.html.erb` | The Stark email layout (replaces upstream's whole file, which is pinned so an upgrade shows its changes). Email texts stay in Settings → Personalization. |
| `lib/stark/current.rb`, `config/initializers/stark.rb` | Who is acting in this request; the share route. |
| `app/controllers/stark/template_visibility_controller.rb`, `app/views/stark/` | Share with company / make private. |
| `db/migrate/…_stark_add_shared_to_templates.rb` | `templates.stark_shared`, false for every existing template. |
| `lib/stark/mcp_oauth.rb`, `app/controllers/stark/mcp_oauth_controller.rb`, `db/migrate/…_stark_create_mcp_oauth.rb` | Claude sign-in for the MCP server (OAuth 2.1 as the MCP specification asks: discovery, client registration, PKCE, rotating refresh tokens). Identity comes from `Stark::Google`, the same code as the web sign-in. |
| `app/controllers/mcp/` | The Stark MCP tools. Each asks the permission question its web or API counterpart asks. |

## Traps

- Every rule in `lib/stark/ability.rb` must be a hash condition. CanCan turns those into SQL for
  lists, search, exports, API indexes and MCP tools; a block-only rule is ignored there.
- Condition values on `:create` rules are lists (`[user.id]`, `[true]`). CanCan pre-fills a new
  record with every scalar value in those conditions: `stark_shared: true` made every template a
  member created start out shared, and the guard then refused to save it.
- A role picker must preselect the user's current role, or saving any other field resets it.
- A column a rule reads must be loaded wherever templates are listed with a narrow `select`
  (patch 0009), or the page fails with "missing attribute".
- `create` on Template is checked twice: on the new template, and on the SOURCE template when
  cloning. Rules are therefore "any new record" or "a template you may read". Never "create per
  account": that let anyone clone any template.
- Ruby shorthand hashes (`account_id:` with no value) at the end of a line continue onto the next
  line. Write `account_id: account_id`.
- Upstream's own Template rule is a scope with a block; CanCan cannot combine it with other rules
  for the same action. Admins keep it untouched; Stark rules replace it for everyone else.
- The template guard only restricts changes made by a signed-in person (`Stark::Current.user`).
  Jobs and the console are not restricted.

## Known gaps, accepted for now

- Members can see that other templates exist in a few places: folder names, the example template
  id on the API settings page, and "you have templates" checks on dashboards. They cannot open,
  list, clone or send those templates.
- Contracts started through a public signing link have no sender, so only admins see them.
- Webhooks are account-wide (admin-only to configure): a webhook receives every contract's events.
- Anyone holding a signer link or a signed copy's link sees that document: upstream's signing model.
- A member can archive their own user (and is then locked out until an admin restores it).
- The author filter on contract lists is empty for members (they may not list users).
- The share-link toggle and the preferences form are visible to a template's author. If a member
  uses them, nothing is saved, but the page can look as if it was (DocuSeal saves them in the
  background and the refusal is a redirect).
- A template can name a fixed recipient for a role (for example legal as counter-signer). That
  person receives the signed copy like any signer. It is visible on the send form, so it is a
  named party, not a hidden copy; template managers and a template's author can set it.
- After a template is shared, its author can still edit it (documents, fields, redirect and
  reply-to settings) and archive it. Sharing approves the author, not a frozen version.
- Senders can delete their own contracts, signed ones included.
- DocuSeal's public "email me my signed copy" page re-sends a completed signer their own copy,
  given a template's link id and that signer's email. It never sends to anyone else, and works
  the same for everyone (no login): upstream's recovery flow, not a Stark role.
- A non-admin's contract carries no BCC of its own, so it follows the template's or account's BCC
  as it is when the contract completes: an admin changing it later also changes it for contracts
  still being signed.
- The MCP server hands a sender their signers' signing links (on a send without email, and while
  following a contract), as the web's "copy link" does. Whoever is given a link can sign as that signer.
- Resending an invitation is not rate-limited (upstream limits it only on its hosted service).
- Inviting a user through the MCP server accepts any address, as the web's users page does; only
  Google sign-in is held to the company domain.
- Members can create templates from a URL through the MCP server; upstream blocks internal
  addresses on that download.
- Google sign-in does not ask for DocuSeal's own two-factor code: the company Google account's
  own sign-in rules (2-step verification) apply instead.
- Only amd64 is tested; the arm64 image is the same files on upstream's arm64 base.
- After a template is made private again, people who sent contracts from it still see those
  contracts, but not the template's own pages (archived list, export).
- Database and S3 administrators see everything.
- Claude connections cannot be listed or ended from the web, and disconnecting in Claude does not end
  one here: it ends when the user is archived, the MCP switch goes off, or 30 days pass.
- Refreshing a Claude connection twice with the same refresh token ends it (a copied token is assumed),
  so a refresh Claude retries after a lost answer means signing in again.
- The Claude sign-in's rate limits are per app process and network address, like upstream's.
- Anyone may register a client, but codes only ever go to Claude's callback addresses; what stops a
  colleague's sign-in link from connecting their Claude to your account is the confirmation page
  naming your user, and Claude checking its own state.

## Settings

Google sign-in is off unless both are set (Google Cloud OAuth client; redirect URI
`https://<host>/identity/connect/oidc-signin`, the path is fixed because it is the one registered):

- `STARK_GOOGLE_CLIENT_ID`, `STARK_GOOGLE_CLIENT_SECRET`
- `STARK_GOOGLE_DOMAIN`: the company domain allowed to sign in (default `starkfuture.com`)
- `STARK_GOOGLE_REDIRECT_URI`: only if the public URL differs from what the app sees
- `STARK_GOOGLE_AUTH_URL`, `_TOKEN_URL`, `_JWKS_URL`: tests only (`tests/google_stub.rb`). Never set
  them in a real environment: they decide whose tokens are trusted.
- `STARK_SOURCE_URL`: the "Source" link (default this repository).

The Claude sign-in uses the same Google client and is off with it. Everything it says and redirects
to is on the public host (`APP_URL`), never the host a request arrived on, because claude.ai reaches
only that one. That host must route `/mcp`, `/.well-known/oauth-protected-resource` (and `/mcp` under
it), `/.well-known/oauth-authorization-server` and `/oauth/*`, and the Google client must also list
`https://<public host>/oauth/google/callback`. `STARK_MCP_OAUTH_REDIRECT_URIS` (space separated)
replaces the callback addresses clients may register (default claude.ai's and claude.com's).

## Upgrading DocuSeal (about once a year)

1. Mirror the new upstream image into ECR keeping the multi-arch index (for example
   `crane copy docuseal/docuseal:<tag> <ecr>/docuseal:<tag>`), then set the tag and digest in
   `UPSTREAM`.
2. `python3 tools/assemble.py`. A PINS mismatch means upstream changed a file we depend on: read
   the change against the intent above, redo the edit on the new upstream file and save it with
   `diff -u --label a/<path> --label b/<path> <old> <new> > patches/<n>.patch`, then update PINS
   (`sha256sum <files>`).
3. Run the tests (below). The route snapshot fails on any new or changed route: check that each new
   endpoint goes through CanCan (or is public by design), then update `tests/routes.txt`.
4. A weekly workflow (`.github/workflows/upstream.yml`) opens an issue labelled `upstream` when Docker Hub
   has a newer release: read its changelog for security fixes and upgrade early when there are some.
   GitHub pauses scheduled workflows after 60 days without repository activity; re-enable it if so.
5. Check where upstream reads `bcc_completed`: today only the contract's, then the template's,
   then the account's (`process_submitter_completion_job.rb`). Upstream also copies it onto
   signers, unused. If a release starts reading the signer copy, guard it too.
6. Read upstream's changelog for new settings pages, API endpoints or MCP tools, and check them
   against the intent above. New MCP tools do not show in the route snapshot (they all live behind
   `/mcp`), but `app/controllers/mcp_controller.rb` is pinned, so a new upstream tool stops the build.

## Testing

CI (`check.yml`) checks the pins and patches and parses every Ruby file on every PR. The permission
tests need a running DocuSeal: `tests/` runs the real image with `build/app` and a throwaway
Postgres (the image staging's own database runs) on a pod in a dynamic sandbox namespace, seeds one
admin, one template manager and two members, and checks 138 allowed and denied cases over the API,
web pages and the built-in MCP server (every tool, every role, another sender's contract, an account
with MCP off), 19 Google sign-in cases against a stand-in Google that signs
tokens with its own key (good, forged, expired, wrong app, wrong issuer, outside domain, unverified,
company address outside the Workspace, replayed, tampered state, archived user, new user), a probe in the pod (contract BCC kept from non-admins and
through signing; linked-account templates admin-only; the email layout; a Google-created user is a member; the MCP invitation email),
the Claude sign-in as claude.ai does it (`tests/mcp_oauth.py`: discovery, registration allowed and
refused, PKCE, code reuse, redirect mismatch, expiry, refresh rotation and reuse, the same refusals as
the web sign-in, the confirmation from another browser, no web session made, a member's token seeing
what its own manual token sees, and role, archiving and the MCP switch applying on the next call), and the route snapshot:

    python3 tools/assemble.py
    bash tests/run_pod_tests.sh sandboxenv-<env>   # recreates the pod, seeds, runs everything
    bash tests/baseline.sh sandboxenv-<env>        # the same on unmodified DocuSeal (matrix only)
    bash tests/cleanup.sh sandboxenv-<env>

## Licence

DocuSeal is AGPL-3.0 with additional terms (`LICENSE`, `LICENSE_ADDITIONAL_TERMS`): the
"Sent using DocuSeal" attribution stays. Because this modified version is offered over a network,
everyone who uses it (staff and signers) must be able to get its corresponding source free of
charge: this repository plus the upstream tag it names, linked as "Source" on every page that shows
the DocuSeal credit. **That link only works once this repository is public.**
