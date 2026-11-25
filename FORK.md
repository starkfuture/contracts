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
- Only template_manager and admin may publish: share a template with the company, or turn on a
  public signing link.
- Only admins assign roles. The first user created at setup is admin.
- The built-in MCP server (`/mcp`, per-user tokens) follows the same rules: it asks the same
  permission class.

## How the fork is built

Upstream source is not copied here. The image is the official DocuSeal image (pinned by digest in
`UPSTREAM` and the `Dockerfile`) plus `build/app/`, which `tools/assemble.py` makes from:

- `patches/`: small edits to upstream files. Each one asserts the exact upstream text it changes
  (`tools/make_patches.py`), and `assemble.py` applies them with no fuzz, so an upstream change in
  a patched spot stops the build instead of drifting silently.
- `overlay/`: Stark's own files (permission rules, the share control, one migration, one route).

| Patch | Upstream file | Why |
|---|---|---|
| 0001 | `lib/ability.rb` | Non-admins get the Stark rules; admins also get `:share`. |
| 0002 | `app/models/user.rb` | Adds the roles; new users default to member. |
| 0003 | `app/controllers/setup_controller.rb` | The first user is admin. |
| 0004 | `app/controllers/users_controller.rb` | Only admins can set a role (no self-promotion). |
| 0005 | `app/views/users/_role_select.html.erb` | The role picker offers the Stark roles. |
| 0006 | `app/controllers/templates_share_link_controller.rb` | A public signing link needs `:share`. |
| 0007 | `app/views/templates/_access_icon.html.erb` | Shows Private/Shared and the share button (empty upstream). |

## Traps

- Every rule in `lib/stark/ability.rb` must be a hash condition. CanCan turns those into SQL for
  lists, search, exports, API indexes and MCP tools; a block-only rule is ignored there and would
  either hide everything or nothing.
- `create` on Submission and Template is per account on purpose: CanCan checks a blank record
  before its creator or author is set.
- Ruby shorthand hashes (`account_id:` with no value) at the end of a line continue onto the next
  line. Write `account_id: account_id`.
- Upstream's own Template rule is a scope with a block; CanCan cannot combine it with other rules
  for the same action. Admins keep it untouched; Stark rules replace it for everyone else.

## Known gaps, accepted for now

- Members can see that other templates exist in a few places: folder names, the author filter list,
  the example template id on the API settings page, and "you have templates" checks on dashboards.
  They cannot open, list or send those templates.
- Webhooks are account-wide (admin-only to configure): a webhook receives every contract's events.
- Anyone holding a signer link or a signed copy's link sees that document. That is upstream's
  signing model and outside these roles.
- Database and S3 administrators see everything.

## Upgrading DocuSeal (about once a year)

1. Set the new tag and image digest in `UPSTREAM` and the `Dockerfile` (ECR mirror first).
2. `python3 tools/make_patches.py <new-src>`: any patch whose upstream text changed fails; re-read
   that upstream change and redo the edit by hand.
3. `python3 tools/assemble.py` must apply every patch cleanly.
4. Run the tests (below). `tests/routes.txt` fails on any new or changed route: check that each new
   endpoint goes through CanCan (or is public by design), then update the snapshot.
5. Read upstream's changelog for new settings pages, API endpoints or MCP tools, and check them
   against the intent above.

## Testing

`tests/` runs the real image with `build/app` on a throwaway Kubernetes pod in a dynamic sandbox
namespace (no registry push needed), seeds one admin, one template manager and two members, and
checks 57 allowed/denied cases over the API, web pages and the MCP server, plus the route snapshot:

    python3 tools/assemble.py
    bash tests/redeploy_pod.sh sandboxenv-<env>
    bash tests/run_pod_tests.sh sandboxenv-<env>
    kubectl --context stark-staging -n sandboxenv-<env> delete pod,configmap -l owner=claude-docuseal-stark

On unmodified DocuSeal the same matrix passes 21 of 57 checks.

## Licence

DocuSeal is AGPL-3.0 with additional terms (`LICENSE`, `LICENSE_ADDITIONAL_TERMS`): the
"Sent using DocuSeal" attribution stays. Because this modified version is offered over a network,
everyone who uses it (staff and signers) must be able to get its corresponding source free of
charge: this repository plus the upstream tag it names.
