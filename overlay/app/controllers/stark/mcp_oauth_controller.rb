# frozen_string_literal: true

module Stark
  # The OAuth authorization server for the built-in MCP server (MCP authorization spec, as claude.ai uses it):
  # discovery, dynamic client registration, authorize -> Google -> one confirmation click -> code, and tokens.
  # People are identified exactly as in the web's Google sign-in (Stark::Google), but no web session is ever
  # read or made: ActionController::API, and the flow lives in its own encrypted cookie.
  class McpOauthController < ActionController::API
    include ActionController::Cookies

    COOKIE = :stark_mcp_oauth
    PKCE_CHALLENGE = /\A[A-Za-z0-9_-]{43}\z/
    PKCE_VERIFIER = /\A[A-Za-z0-9\-._~]{43,128}\z/

    before_action { head :not_found unless Stark::Google.enabled? }
    # Per network address (claude.ai registers and exchanges tokens from its own servers).
    before_action(only: :register) { rate_limit!('register', 30) }
    before_action(only: :callback) { rate_limit!('callback', 30) } # each one costs a call to Google
    before_action(only: :token) { rate_limit!('token', 60) }
    rescue_from(RateLimit::LimitApproached) { render json: { error: 'too_many_requests' }, status: :too_many_requests }

    # RFC 9728
    def protected_resource
      render json: { resource: McpOauth.resource, authorization_servers: [McpOauth.base_url],
                     bearer_methods_supported: ['header'] }
    end

    # RFC 8414
    def authorization_server
      base = McpOauth.base_url
      render json: { issuer: base, authorization_endpoint: "#{base}/oauth/authorize",
                     token_endpoint: "#{base}/oauth/token", registration_endpoint: "#{base}/oauth/register",
                     response_types_supported: ['code'], grant_types_supported: %w[authorization_code refresh_token],
                     code_challenge_methods_supported: ['S256'], token_endpoint_auth_methods_supported: ['none'] }
    end

    # RFC 7591. Public clients only: whatever authentication a client asks for, it gets none (no secret).
    def register
      body = JSON.parse(request.raw_post.presence || '{}')
      uris = body['redirect_uris'] if body.is_a?(Hash)
      unless uris.is_a?(Array) && uris.size.between?(1, 5) && uris.all?(String) &&
             (uris - McpOauth.allowed_redirect_uris).empty?
        return oauth_error('invalid_redirect_uri')
      end

      # Anyone may register; a client that never got a grant is dropped after a day.
      McpOauth::Client.where(created_at: ...1.day.ago).where.not(id: McpOauth::Grant.select(:client_id)).delete_all
      client = McpOauth::Client.create!(client_id: McpOauth.random, redirect_uris: uris.uniq,
                                        client_name: body['client_name'].to_s.first(100).presence)
      render status: :created, json: {
        client_id: client.client_id, client_id_issued_at: client.created_at.to_i, client_name: client.client_name,
        redirect_uris: client.redirect_uris, grant_types: %w[authorization_code refresh_token],
        response_types: ['code'], token_endpoint_auth_method: 'none'
      }.compact
    rescue JSON::ParserError
      oauth_error('invalid_client_metadata')
    end

    def authorize
      client = McpOauth::Client.find_by(client_id: text(:client_id))
      redirect_uri = text(:redirect_uri)
      # Never redirect to an address the client did not register: no open redirect.
      return render(plain: 'Unknown client or redirect address.', status: :bad_request) unless
        redirect_uri && client&.redirect_uris&.include?(redirect_uri)

      state = text(:state)
      error = if text(:response_type) != 'code' then 'unsupported_response_type'
              elsif !text(:code_challenge).to_s.match?(PKCE_CHALLENGE) || text(:code_challenge_method) != 'S256' ||
                    (params.key?(:state) && (state.nil? || state.size > 512))
                'invalid_request'
              elsif params.key?(:resource) && !McpOauth.resource?(params[:resource]) then 'invalid_target'
              end
      return back_to(redirect_uri, state, error:) if error

      flow = { 'client' => client.id, 'redirect_uri' => redirect_uri, 'challenge' => text(:code_challenge),
               'state' => state, 'google_state' => McpOauth.random, 'nonce' => McpOauth.random }
      write_flow(flow)
      redirect_to Stark::Google.authorize_url(redirect_uri: McpOauth.callback_url, state: flow['google_state'],
                                              nonce: flow['nonce']), allow_other_host: true
    end

    # Back from Google. Only the browser that started at /oauth/authorize holds the cookie, so a link to Google
    # sent to someone else goes nowhere.
    def callback
      flow = take_flow
      unless flow&.dig('google_state') &&
             ActiveSupport::SecurityUtils.secure_compare(params[:state].to_s, flow['google_state'])
        return render(plain: 'That sign-in link expired. Start again from Claude.', status: :bad_request)
      end

      claims = Stark::Google.claims_for(code: params[:code].to_s, redirect_uri: McpOauth.callback_url,
                                        nonce: flow['nonce'])
      user = Stark::Google.find_or_create_user(claims)
      return refuse(flow, "user #{user.id} may not use the MCP server") unless McpOauth.allowed?(user)

      flow = flow.except('google_state', 'nonce').merge('user' => user.id, 'key' => McpOauth.random)
      write_flow(flow)
      confirm_page(user, McpOauth::Client.find_by(id: flow['client']), flow)
    rescue Stark::Google::Error => e
      refuse(flow, "google: #{e.message}")
    end

    # The confirmation click. Google's account chooser says who you are, not that you want Claude to act as you:
    # without this, a colleague's authorize link could connect their Claude to your account.
    def consent
      flow = take_flow
      unless flow&.dig('key') && ActiveSupport::SecurityUtils.secure_compare(params[:key].to_s, flow['key'])
        return render(plain: 'That sign-in link expired. Start again from Claude.', status: :bad_request)
      end

      user = User.find_by(id: flow['user'])
      client = McpOauth::Client.find_by(id: flow['client'])
      return refuse(flow, 'declined') unless params[:allow].present?
      return refuse(flow, "user #{flow['user']} may not use the MCP server") unless client && McpOauth.allowed?(user)

      code = McpOauth.random
      McpOauth::Grant.where(expires_at: ...Time.current).delete_all
      McpOauth::Grant.create!(client:, user:, redirect_uri: flow['redirect_uri'], code_challenge: flow['challenge'],
                              resource: McpOauth.resource, code_sha256: McpOauth.digest(code),
                              code_expires_at: McpOauth::CODE_TTL.from_now, expires_at: McpOauth::GRANT_TTL.from_now)
      Rails.logger.info("stark mcp oauth: user #{user.id} connected client #{client.id}")
      back_to(flow['redirect_uri'], flow['state'], code:)
    end

    def token
      response.headers['Cache-Control'] = 'no-store'
      response.headers['Pragma'] = 'no-cache'
      case params[:grant_type]
      when 'authorization_code' then exchange_code
      when 'refresh_token' then refresh
      else oauth_error('unsupported_grant_type')
      end
    end

    private

    def exchange_code
      sha = McpOauth.digest(params[:code])
      # The first attempt uses the code up, right or wrong. A second use means someone else has it: the tokens
      # already issued from it stop working too.
      unless McpOauth::Grant.where(code_sha256: sha, code_used_at: nil).update_all(code_used_at: Time.current) == 1
        McpOauth::Grant.where(code_sha256: sha).update_all(revoked_at: Time.current)
        return oauth_error('invalid_grant')
      end

      grant = McpOauth::Grant.find_by!(code_sha256: sha)
      verifier = params[:code_verifier].to_s
      ok = grant.revoked_at.nil? && grant.code_expires_at.future? && grant.client.client_id == client_id &&
           grant.redirect_uri == params[:redirect_uri].to_s && verifier.match?(PKCE_VERIFIER) &&
           ActiveSupport::SecurityUtils.secure_compare(
             Base64.urlsafe_encode64(Digest::SHA256.digest(verifier), padding: false), grant.code_challenge
           ) && resource_ok? && McpOauth.allowed?(grant.user)
      ok ? render(json: McpOauth.issue_tokens!(grant)) : oauth_error('invalid_grant')
    end

    # Rotation: each refresh token works once. The one before it, used again, ends the whole connection
    # (RFC 9700 4.14); the lock makes two refreshes with the same token count as one reuse.
    def refresh
      sha = McpOauth.digest(params[:refresh_token])
      tokens = McpOauth::Grant.transaction do
        grant = McpOauth::Grant.lock.find_by(refresh_sha256: sha)
        if grant.nil?
          McpOauth::Grant.where(previous_refresh_sha256: sha).update_all(revoked_at: Time.current)
          nil
        elsif grant.revoked_at.nil? && grant.expires_at.future? && grant.client.client_id == client_id &&
              resource_ok? && McpOauth.allowed?(grant.user)
          McpOauth.issue_tokens!(grant)
        end
      end
      tokens ? render(json: tokens) : oauth_error('invalid_grant')
    end

    # Public clients send client_id in the form; tolerate a client that sends it as HTTP Basic anyway.
    def client_id
      return params[:client_id].to_s if params[:client_id].present?
      return '' unless request.authorization.to_s.start_with?('Basic ')

      ActionController::HttpAuthentication::Basic.user_name_and_password(request).first.to_s
    end

    def resource_ok?
      !params.key?(:resource) || McpOauth.resource?(params[:resource])
    end

    def text(key)
      params[key] if params[key].is_a?(String)
    end

    def write_flow(flow)
      cookies.encrypted[COOKIE] = { value: flow, expires: McpOauth::FLOW_TTL, httponly: true, same_site: :lax,
                                    path: '/oauth', secure: McpOauth.base_url.start_with?('https:') }
    end

    def take_flow
      flow = cookies.encrypted[COOKIE]
      cookies.delete(COOKIE, path: '/oauth')
      flow if flow.is_a?(Hash)
    end

    def back_to(uri, state, **query)
      url = URI(uri)
      url.query = [url.query.presence, query.merge(state:).compact.to_query].compact.join('&')
      redirect_to url.to_s, allow_other_host: true
    end

    # Once the client is known, refusals go back to it, so Claude can say the connection failed.
    def refuse(flow, reason)
      Rails.logger.warn("stark mcp oauth refused: #{reason}")
      return render(plain: 'Sign-in failed.', status: :bad_request) unless flow&.dig('redirect_uri')

      back_to(flow['redirect_uri'], flow['state'], error: 'access_denied')
    end

    def oauth_error(error)
      render json: { error: }, status: :bad_request
    end

    def rate_limit!(name, limit)
      RateLimit.call("stark-mcp-oauth-#{name}-#{request.remote_ip}", limit:, ttl: 1.minute, enabled: true)
    end

    def confirm_page(user, client, flow)
      h = ->(s) { ERB::Util.html_escape(s.to_s) }
      app = "#{client&.client_name.presence || 'An app'} (#{URI(flow['redirect_uri']).host})"
      response.headers['X-Frame-Options'] = 'DENY'
      response.headers['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; " \
                                                    "form-action 'self'; frame-ancestors 'none'"
      render html: <<~HTML.html_safe # rubocop:disable Rails/OutputSafety -- every value is escaped
        <!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Connect to Stark DocuSeal</title></head>
        <body style="font-family:system-ui,sans-serif;max-width:30rem;margin:4rem auto;padding:0 1rem;line-height:1.5">
        <h1 style="font-size:1.4rem">Connect #{h.(app)} to DocuSeal?</h1>
        <p>It will act as <b>#{h.(user.email)}</b> (#{h.(user.role.to_s.humanize.downcase)}) with exactly your DocuSeal
        rights, for up to 30 days or until an admin archives your user.</p>
        <form method="post" action="/oauth/consent"><input type="hidden" name="key" value="#{h.(flow['key'])}">
        <button name="allow" value="1" style="font-size:1rem;padding:.5rem 1.5rem">Allow</button>
        <button name="deny" value="1" style="font-size:1rem;padding:.5rem 1rem">Cancel</button></form></body></html>
      HTML
    end
  end
end
