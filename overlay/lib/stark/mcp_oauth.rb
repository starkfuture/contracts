# frozen_string_literal: true

module Stark
  # OAuth 2.1 for the built-in MCP server, so a claude.ai connector signs in with company Google and acts as
  # that person's DocuSeal user (Stark::McpOauthController issues, Mcp::McpBaseController accepts).
  # Codes and tokens are random; only their sha256 is stored.
  module McpOauth
    CODE_TTL = 60.seconds
    ACCESS_TTL = 1.hour
    # Absolute: a person signs in with Google again at least this often, which bounds how long a connection
    # outlives their company Google account.
    GRANT_TTL = 30.days
    FLOW_TTL = 10.minutes
    CALLBACK_PATH = '/oauth/google/callback'
    # Codes only ever travel to these, so registering a client gains an outsider nothing.
    DEFAULT_REDIRECT_URIS = %w[https://claude.ai/api/mcp/auth_callback https://claude.com/api/mcp/auth_callback].freeze

    class Client < ApplicationRecord
      self.table_name = 'stark_mcp_oauth_clients'
      serialize :redirect_uris, coder: JSON
      has_many :grants, class_name: 'Stark::McpOauth::Grant', dependent: :delete_all
    end

    # One sign-in: its authorization code, then the access and refresh tokens it rotates through.
    class Grant < ApplicationRecord
      self.table_name = 'stark_mcp_oauth_grants'
      belongs_to :client, class_name: 'Stark::McpOauth::Client'
      belongs_to :user
      scope :live, -> { where(revoked_at: nil).where('expires_at > ?', Time.current) }
    end

    # Every refresh token a grant has already exchanged, so that any of them coming back ends the grant.
    class UsedRefreshToken < ApplicationRecord
      self.table_name = 'stark_mcp_oauth_used_refresh_tokens'
      belongs_to :grant, class_name: 'Stark::McpOauth::Grant'
    end

    module_function

    # The public host (APP_URL), never the request's Host header: claude.ai reaches only that one.
    def base_url
      o = Docuseal.default_url_options
      port = ":#{o[:port]}" if o[:port].present? && o[:port].to_i != (o[:protocol] == 'https' ? 443 : 80)
      "#{o[:protocol]}://#{o[:host]}#{port}"
    end

    def resource
      "#{base_url}/mcp"
    end

    def resource?(value)
      value.is_a?(String) && value.chomp('/') == resource
    end

    def resource_metadata_url
      "#{base_url}/.well-known/oauth-protected-resource"
    end

    def callback_url
      "#{base_url}#{CALLBACK_PATH}"
    end

    def allowed_redirect_uris
      ENV['STARK_MCP_OAUTH_REDIRECT_URIS'].to_s.split(/[\s,]+/).compact_blank.presence || DEFAULT_REDIRECT_URIS
    end

    def digest(value)
      Digest::SHA256.hexdigest(value.to_s)
    end

    def random
      SecureRandom.urlsafe_base64(32)
    end

    # Who may connect: anyone who may sign in, in an account with the MCP server on (as
    # Mcp::McpBaseController#verify_mcp_enabled!), with the :mcp ability.
    def allowed?(user)
      user.present? && user.active_for_authentication? &&
        (Docuseal.multitenant? ||
         AccountConfig.exists?(account_id: user.account_id, key: AccountConfig::ENABLE_MCP_KEY, value: true)) &&
        ::Ability.new(user).can?(:manage, :mcp)
    end

    # The user an access token acts as; nil once it expired, its grant ended, or the user may no longer sign in.
    def user_for_access_token(sha256)
      user = Grant.live.where(resource: resource).where('access_expires_at > ?', Time.current)
                  .find_by(access_sha256: sha256)&.user
      user if user&.active_for_authentication?
    end

    # New access and refresh tokens; the previous ones stop working. The spent refresh token is kept to notice
    # it being used again.
    def issue_tokens!(grant)
      access = random
      refresh = random
      UsedRefreshToken.create!(grant:, sha256: grant.refresh_sha256) if grant.refresh_sha256
      grant.update!(access_sha256: digest(access), access_expires_at: [ACCESS_TTL.from_now, grant.expires_at].min,
                    refresh_sha256: digest(refresh))
      { access_token: access, token_type: 'Bearer', expires_in: (grant.access_expires_at - Time.current).to_i,
        refresh_token: refresh }
    end
  end
end
