# frozen_string_literal: true

module Mcp
  # Stark: invite a user, as an admin does on the users page (UsersController#create), with the upstream
  # invitation email that lets them set a password.
  class InviteUserController < McpBaseController
    SCHEMA = {
      name: 'invite_user',
      title: 'Invite User',
      description: 'Create a user and email them an invitation. Role defaults to member. Admins only.',
      inputSchema: {
        type: 'object',
        properties: {
          email: { type: 'string', description: 'Email address' },
          first_name: { type: 'string', description: 'First name' },
          last_name: { type: 'string', description: 'Last name' },
          role: { type: 'string', enum: User::ROLES, description: 'Role (default member)' }
        },
        required: %w[email first_name last_name]
      },
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true }
    }.freeze

    def call
      role = mcp_params['role'].presence || User::MEMBER_ROLE
      user = current_user.account.users.new(email: mcp_params['email'].to_s.strip.downcase, role:,
                                            first_name: mcp_params['first_name'], last_name: mcp_params['last_name'])

      authorize!(:create, user)

      # Upstream turns an unknown role into admin; refuse it instead.
      return render_tool_error("role must be one of #{User::ROLES.join(', ')}") unless role.in?(User::ROLES)

      existing = User.accessible_by(current_ability).find_by(email: user.email)

      if existing
        return render_tool_error('A user with this email already exists') unless existing.archived_at?

        # As upstream: inviting an archived user restores them with the new name and role, and a new
        # random password (the invitation lets them set theirs).
        existing.assign_attributes(user.slice(:first_name, :last_name, :role))
        existing.archived_at = nil
        user = existing
      end

      user.password = SecureRandom.hex

      return render_tool_error(user.errors.full_messages.join(', ')) unless user.save

      UserMailer.invitation_email(user).deliver_later!

      render_tool_result(user.slice(:id, :email, :first_name, :last_name, :role))
    end
  end
end
