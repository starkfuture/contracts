# frozen_string_literal: true

module Mcp
  # Stark: change a user's role, as an admin editing a user (UsersController#update). Nobody changes
  # their own role (upstream drops it when people edit themselves), so the last admin cannot demote itself.
  class SetUserRoleController < McpBaseController
    SCHEMA = {
      name: 'set_user_role',
      title: 'Set User Role',
      description: 'Change a user\'s role: member (own contracts, own and shared templates), template_manager ' \
                   '(also every template, and sharing) or admin (everything). Admins only; not your own role.',
      inputSchema: {
        type: 'object',
        properties: {
          user_id: { type: 'integer', description: 'User identifier, from list_users' },
          role: { type: 'string', enum: User::ROLES, description: 'New role' }
        },
        required: %w[user_id role]
      },
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    }.freeze

    def call
      # As UsersController (load_and_authorize_resource): find, then ask CanCan.
      user = User.find(mcp_params['user_id'])

      authorize!(:update, user)
      raise CanCan::AccessDenied if user.id == current_user.id

      unless mcp_params['role'].in?(User::ROLES)
        return render_tool_error("role must be one of #{User::ROLES.join(', ')}")
      end

      user.update!(role: mcp_params['role'])

      render_tool_result(user.slice(:id, :email, :role))
    end
  end
end
