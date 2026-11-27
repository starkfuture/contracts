# frozen_string_literal: true

module Mcp
  # Stark: the users list, admin only (as UsersController#index).
  class ListUsersController < McpBaseController
    SCHEMA = {
      name: 'list_users',
      title: 'List Users',
      description: 'List the active users of the account with their role. Admins only.',
      inputSchema: { type: 'object', properties: {} },
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    }.freeze

    def call
      authorize!(:index, User)

      users = User.accessible_by(current_ability).where(account_id: current_user.account_id)
                  .active.where.not(role: 'integration').order(:id)

      render_tool_result(users.map { |u| u.slice(:id, :email, :first_name, :last_name, :role, :last_sign_in_at) })
    end
  end
end
