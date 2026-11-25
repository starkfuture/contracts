#!/usr/bin/env python3
"""Regenerate patches/ from an upstream checkout: python3 tools/make_patches.py <upstream-src-dir>

Each patch is one small, named edit to an upstream file. Every edit asserts the exact upstream text it
replaces, so a DocuSeal upgrade that changed that text fails here instead of silently drifting.
"""
import os, shutil, subprocess, sys, tempfile

SRC = sys.argv[1]
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "patches")

EDITS = [
    ("0001-ability-stark-roles.patch", "lib/ability.rb", [
        ("  def initialize(user)\n",
         "  def initialize(user)\n"
         "    # Stark: every role but admin gets the scoped rules in lib/stark/ability.rb.\n"
         "    return Stark::Ability.call(self, user) unless user.role == User::ADMIN_ROLE\n\n"
         "    # Stark: admins may share templates within the company (template_manager has it via :manage).\n"
         "    can :share, Template, account_id: user.account_id\n\n"),
    ]),
    ("0002-user-roles.patch", "app/models/user.rb", [
        ("  ROLES = [\n    ADMIN_ROLE = 'admin'\n  ].freeze\n",
         "  ROLES = [\n    ADMIN_ROLE = 'admin',\n"
         "    # Stark roles (lib/stark/ability.rb).\n"
         "    TEMPLATE_MANAGER_ROLE = 'template_manager',\n    MEMBER_ROLE = 'member'\n  ].freeze\n"),
        ("  attribute :role, :string, default: ADMIN_ROLE\n",
         "  # Stark: least privilege by default; the first user is made admin by SetupController.\n"
         "  attribute :role, :string, default: MEMBER_ROLE\n"),
    ]),
    ("0003-setup-first-user-admin.patch", "app/controllers/setup_controller.rb", [
        ("  def create\n    @account = Account.new(account_params)\n    @account.timezone = Accounts.normalize_timezone(@account.timezone)\n"
         "    @user = @account.users.new(user_params)\n",
         "  def create\n    @account = Account.new(account_params)\n    @account.timezone = Accounts.normalize_timezone(@account.timezone)\n"
         "    @user = @account.users.new(user_params.merge(role: User::ADMIN_ROLE)) # Stark: first user is admin\n"),
    ]),
    ("0004-users-role-admin-only.patch", "app/controllers/users_controller.rb", [
        ("      permitted_params << :role if role_valid?(params.dig(:user, :role))\n",
         "      # Stark: only admins assign roles; a member editing their own user cannot promote themselves.\n"
         "      permitted_params << :role if current_user.role == User::ADMIN_ROLE && role_valid?(params.dig(:user, :role))\n"),
    ]),
    ("0005-role-select-stark-roles.patch", "app/views/users/_role_select.html.erb", [
        ("    <option value=\"admin\"><%= t('admin') %></option>\n"
         "    <option value=\"editor\" disabled><%= t('editor') %></option>\n"
         "    <option value=\"viewer\" disabled><%= t('viewer') %></option>\n",
         "    <option value=\"member\">Member: own contracts, own and shared templates</option>\n"
         "    <option value=\"template_manager\">Template manager: all templates, own contracts</option>\n"
         "    <option value=\"admin\"><%= t('admin') %>: everything, settings and users</option>\n"),
    ]),
    ("0006-share-link-needs-share.patch", "app/controllers/templates_share_link_controller.rb", [
        ("  def create\n    authorize!(:update, @template)\n",
         "  def create\n    authorize!(:share, @template) # Stark: a public signing link is publishing\n"),
    ]),
    ("0007-access-icon-stark-visibility.patch", "app/views/templates/_access_icon.html.erb", [
        ("", "<%= render 'stark/template_visibility', template: %>\n"),
    ]),
]

os.makedirs(OUT, exist_ok=True)
for name in os.listdir(OUT):
    os.remove(os.path.join(OUT, name))
with tempfile.TemporaryDirectory() as tmp:
    for patch, path, edits in EDITS:
        a, b = os.path.join(tmp, "a", path), os.path.join(tmp, "b", path)
        os.makedirs(os.path.dirname(a), exist_ok=True)
        os.makedirs(os.path.dirname(b), exist_ok=True)
        shutil.copy(os.path.join(SRC, path), a)
        text = open(a).read()
        for old, new in edits:
            if old == "":
                assert text == "", f"{path}: expected an empty upstream file"
                text = new
            else:
                assert text.count(old) == 1, f"{path}: upstream text changed, review this patch: {old[:60]!r}"
                text = text.replace(old, new)
        open(b, "w").write(text)
        diff = subprocess.run(["diff", "-u", "--label", f"a/{path}", "--label", f"b/{path}", f"a/{path}", f"b/{path}"], cwd=tmp, capture_output=True, text=True).stdout
        assert diff, path
        open(os.path.join(OUT, patch), "w").write(diff)
        print("wrote", patch)
