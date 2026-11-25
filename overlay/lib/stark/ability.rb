# frozen_string_literal: true

# Stark permissions for every role except admin (admins keep DocuSeal's own rules: everything in
# the account). Called from the first line of Ability#initialize (patches/0001).
#
# Intent:
# - member: sees and sends only their own contracts; sees their own templates and the templates
#   shared within the company; edits only their own templates; no settings.
# - template_manager: as member for contracts; sees, creates, edits and shares every template.
# - Templates are private until a template_manager or admin shares them (Template#stark_shared).
# - Seeing a template never grants seeing other people's contracts made from it.
#
# Every rule is a hash condition, so CanCan's accessible_by turns it into SQL for every list,
# search, export, API index and MCP tool. Never add a block-only rule: it would be skipped there.
module Stark
  module Ability
    module_function

    def call(ability, user)
      account_id = user.account_id

      templates(ability, user, account_id)

      # Contracts: only the ones this person sent. `create` is checked on a blank Submission,
      # before its creator is set, so it is granted for new records (id: nil); reading the template
      # it is made from is checked separately by the controllers.
      ability.can %i[read update destroy], Submission, account_id: account_id, created_by_user_id: user.id
      ability.can :create, Submission, account_id: account_id, id: nil
      ability.can :manage, Submitter, account_id: account_id, submission: { created_by_user_id: user.id }

      # Their own profile, preferences, API key and MCP tokens. Role changes are refused in
      # UsersController (patches/0004), so managing their own user cannot make them admin.
      ability.can :manage, User, id: user.id, account_id: account_id
      ability.can :manage, UserConfig, user_id: user.id
      ability.can :manage, EncryptedUserConfig, user_id: user.id
      ability.can :manage, AccessToken, user_id: user.id
      ability.can :manage, McpToken, user_id: user.id
      ability.can :manage, :mcp
      # Managing their own user covers the profile page; the list of users is admin-only.
      ability.cannot :index, User
      # No AccountConfig, EncryptedConfig, WebhookUrl, Account or TemplateSharing rights: every
      # account setting (email texts, notifications, SMTP, storage, webhooks, users) is admin-only.
    end

    def templates(ability, user, account_id)
      if user.role == User::TEMPLATE_MANAGER_ROLE
        ability.can :manage, Template, account_id: account_id
        ability.can :manage, TemplateFolder, account_id: account_id
        return
      end

      readable = [{ author_id: user.id }, { stark_shared: true }]
      readable.each { |c| ability.can :read, Template, c.merge(account_id: account_id) }
      # `create` is checked twice: on a new template (its author is set after the check), and on the
      # SOURCE template when cloning (TemplatesClone*, Api::TemplatesClone). So: any new record, or a
      # clone of a template this person may read. Never "create per account": that clones anything.
      ability.can :create, Template, account_id: account_id, id: nil
      readable.each { |c| ability.can :create, Template, c.merge(account_id: account_id) }
      ability.can %i[update destroy], Template, account_id: account_id, author_id: user.id

      # Folder names are visible to everyone in the account (templates inside stay filtered).
      ability.can %i[read create], TemplateFolder, account_id: account_id
      ability.can %i[update destroy], TemplateFolder, account_id: account_id, author_id: user.id
    end
  end
end
