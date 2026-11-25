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
- Only admins assign roles. The first user created at setup is admin. Existing users keep the role
  they had: after the first deploy every pre-existing user is still admin until an admin changes it.
- The built-in MCP server (`/mcp`, per-user tokens) follows the same rules: it asks the same
  permission class.

## How the fork is built

Upstream source is not copied here. The image is the official DocuSeal image (the multi-arch index
mirrored in ECR, pinned by digest in `UPSTREAM` and passed to the `Dockerfile` as `BASE`) plus
`build/app/`, which `tools/assemble.py` makes from:

- `PINS`: sha256 of the full upstream content of every file we patch, plus the permission rules
  Stark replaces for non-admins (`lib/ability.rb`, `lib/abilities/template_conditions.rb`). Any
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

| Stark file | What |
|---|---|
| `lib/stark/ability.rb` | The rules for member and template_manager. |
| `lib/stark/template_guard.rb` | Publishing, a template's BCC and permanent delete, enforced on the model so every path (web, API, MCP, clone) is covered. |
| `lib/stark/submission_guard.rb` | A contract's own BCC from anyone but an admin is dropped (the template's or account's applies). |
| `config/locales/stark.en.yml` | Role names in the users list. |
| `lib/stark/current.rb`, `config/initializers/stark.rb` | Who is acting in this request; the share route. |
| `app/controllers/stark/template_visibility_controller.rb`, `app/views/stark/` | Share with company / make private. |
| `db/migrate/…_stark_add_shared_to_templates.rb` | `templates.stark_shared`, false for every existing template. |

## Traps

- Every rule in `lib/stark/ability.rb` must be a hash condition. CanCan turns those into SQL for
  lists, search, exports, API indexes and MCP tools; a block-only rule is ignored there.
- Condition values on `:create` rules are lists (`[user.id]`, `[true]`). CanCan pre-fills a new
  record with every scalar value in those conditions: `stark_shared: true` made every template a
  member created start out shared, and the guard then refused to save it.
- A role picker must preselect the user's current role, or saving any other field resets it.
- A column a rule reads must be loaded wherever templates are listed with a narrow `select`
  (patch 0012), or the page fails with "missing attribute".
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
- Only amd64 is tested; the arm64 image is the same files on upstream's arm64 base.
- After a template is made private again, people who sent contracts from it still see those
  contracts, but not the template's own pages (archived list, export).
- Database and S3 administrators see everything.

## Upgrading DocuSeal (about once a year)

1. Mirror the new upstream image into ECR keeping the multi-arch index (for example
   `crane copy docuseal/docuseal:<tag> <ecr>/docuseal:<tag>`), then set the tag and digest in
   `UPSTREAM` and the `Dockerfile`.
2. `python3 tools/assemble.py`. A PINS mismatch means upstream changed a file we depend on: read
   the change against the intent above, redo the edit on the new upstream file and save it with
   `diff -u --label a/<path> --label b/<path> <old> <new> > patches/<n>.patch`, then update PINS
   (`sha256sum <files>`).
3. Run the tests (below). The route snapshot fails on any new or changed route: check that each new
   endpoint goes through CanCan (or is public by design), then update `tests/routes.txt`.
4. Read upstream's changelog for new settings pages, API endpoints or MCP tools, and check them
   against the intent above. New MCP tools do not show in the route snapshot (they all live behind
   `/mcp`): list them in `app/controllers/mcp_controller.rb`.

## Testing

CI (`check.yml`) checks the pins and patches and parses every Ruby file on every PR. The permission
tests need a running DocuSeal: `tests/` runs the real image with `build/app` and a throwaway
Postgres (the image staging's own database runs) on a pod in a dynamic sandbox namespace, seeds one
admin, one template manager and two members, and checks 79 allowed and denied cases over the API,
web pages and the built-in MCP server, a probe of what the API does not return (contract BCC), and
the 251-route snapshot:

    python3 tools/assemble.py
    bash tests/run_pod_tests.sh sandboxenv-<env>   # recreates the pod, seeds, runs everything
    bash tests/baseline.sh sandboxenv-<env>        # the same on unmodified DocuSeal: 28/79
    bash tests/cleanup.sh sandboxenv-<env>

## Licence

DocuSeal is AGPL-3.0 with additional terms (`LICENSE`, `LICENSE_ADDITIONAL_TERMS`): the
"Sent using DocuSeal" attribution stays. Because this modified version is offered over a network,
everyone who uses it (staff and signers) must be able to get its corresponding source free of
charge: this repository plus the upstream tag it names, linked as "Source" on every page that shows
the DocuSeal credit. **That link only works once this repository is public.**
