# frozen_string_literal: true

require 'net/http'

module Stark
  # Sign in with Google (OpenID Connect, authorization-code flow), written against Google's endpoints
  # with the jwt gem DocuSeal already ships: no new gem, so the image stays a plain COPY.
  # Off unless STARK_GOOGLE_CLIENT_ID and STARK_GOOGLE_CLIENT_SECRET are set.
  module Google
    AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
    TOKEN_URL = 'https://oauth2.googleapis.com/token'
    JWKS_URL = 'https://www.googleapis.com/oauth2/v3/certs'
    ISSUERS = ['https://accounts.google.com', 'accounts.google.com'].freeze
    CALLBACK_PATH = '/identity/connect/oidc-signin'

    Error = Class.new(StandardError)

    module_function

    def enabled?
      client_id.present? && ENV['STARK_GOOGLE_CLIENT_SECRET'].present?
    end

    def client_id
      ENV.fetch('STARK_GOOGLE_CLIENT_ID', nil)
    end

    # Only people with an address in this Google Workspace domain may sign in.
    def domain
      ENV.fetch('STARK_GOOGLE_DOMAIN', 'starkfuture.com').downcase
    end

    # The three endpoints can be pointed elsewhere for tests only (tests/google_stub.rb).
    def endpoint(name, default)
      ENV.fetch("STARK_GOOGLE_#{name}_URL", default)
    end

    def authorize_url(redirect_uri:, state:, nonce:)
      query = { client_id:, redirect_uri:, response_type: 'code', scope: 'openid email profile',
                state:, nonce:, hd: domain, prompt: 'select_account' }
      "#{endpoint('AUTH', AUTH_URL)}?#{query.to_query}"
    end

    # Exchanges the code and returns the verified ID token claims. Raises Error on anything off.
    def claims_for(code:, redirect_uri:, nonce:)
      response = Net::HTTP.post_form(URI(endpoint('TOKEN', TOKEN_URL)),
                                     code:, redirect_uri:, client_id:, grant_type: 'authorization_code',
                                     client_secret: ENV.fetch('STARK_GOOGLE_CLIENT_SECRET'))
      raise Error, "token endpoint returned #{response.code}" unless response.is_a?(Net::HTTPSuccess)

      id_token = JSON.parse(response.body)['id_token'] or raise Error, 'no id_token'
      claims, = JWT.decode(id_token, nil, true, algorithms: ['RS256'], jwks: jwks,
                                                iss: ISSUERS, verify_iss: true, aud: client_id, verify_aud: true)
      check!(claims, nonce)
    rescue JWT::DecodeError, JSON::ParserError => e
      raise Error, e.class.name
    end

    # Signature, issuer, audience and expiry are checked by JWT.decode; the rest here. The email's own
    # domain is checked too: `hd` alone says which Workspace the account belongs to, not the address.
    def check!(claims, nonce)
      email = claims['email'].to_s.downcase
      raise Error, 'nonce mismatch' unless ActiveSupport::SecurityUtils.secure_compare(claims['nonce'].to_s, nonce.to_s)
      raise Error, 'email not verified' unless claims['email_verified'] == true
      raise Error, 'outside the company domain' unless claims['hd'].to_s.downcase == domain && email.end_with?("@#{domain}")

      claims.merge('email' => email)
    end

    def jwks
      Rails.cache.fetch('stark/google/jwks', expires_in: 1.hour) do
        JSON.parse(Net::HTTP.get(URI(endpoint('JWKS', JWKS_URL))))
      end
    end
  end
end
