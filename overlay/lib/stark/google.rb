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
    TEST_HOSTS = %w[127.0.0.1 localhost].freeze
    TIMEOUT = 5

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

    # The endpoints decide whose tokens are trusted. They can be redirected for tests only
    # (tests/google_stub.rb), and only to this machine: any other override is ignored.
    def endpoint(name, default)
      url = ENV.fetch("STARK_GOOGLE_#{name}_URL", nil)
      url.present? && URI(url).host.in?(TEST_HOSTS) ? url : default
    end

    def authorize_url(redirect_uri:, state:, nonce:)
      query = { client_id:, redirect_uri:, response_type: 'code', scope: 'openid email profile',
                state:, nonce:, hd: domain, prompt: 'select_account' }
      "#{endpoint('AUTH', AUTH_URL)}?#{query.to_query}"
    end

    # Exchanges the code and returns the verified ID token claims. Raises Error on anything off.
    def claims_for(code:, redirect_uri:, nonce:)
      response = http(:post, endpoint('TOKEN', TOKEN_URL),
                      { code:, redirect_uri:, client_id:, grant_type: 'authorization_code',
                        client_secret: ENV.fetch('STARK_GOOGLE_CLIENT_SECRET') })
      raise Error, "token endpoint returned #{response.code}" unless response.is_a?(Net::HTTPSuccess)

      id_token = JSON.parse(response.body)['id_token'] or raise Error, 'no id_token'
      claims, = JWT.decode(id_token, nil, true, algorithms: ['RS256'], jwks: method(:jwks),
                                                iss: ISSUERS, verify_iss: true, aud: client_id, verify_aud: true)
      check!(claims, nonce)
    rescue JWT::DecodeError, JSON::ParserError, IOError, SystemCallError, SocketError, Timeout::Error,
           OpenSSL::SSL::SSLError => e
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

    # Google's signing keys, cached for an hour. A token signed with a key we have not seen (Google
    # rotated) refetches once, at most every five minutes. Only a well-formed key set is cached.
    def jwks(options = {})
      if options[:kid_not_found] && Rails.cache.write('stark/google/jwks_refetched', true, expires_in: 5.minutes,
                                                                                         unless_exist: true)
        Rails.cache.delete('stark/google/jwks')
      end
      Rails.cache.fetch('stark/google/jwks', expires_in: 1.hour) do
        response = http(:get, endpoint('JWKS', JWKS_URL))
        keys = response.is_a?(Net::HTTPSuccess) && JSON.parse(response.body)
        raise Error, 'bad key set' unless keys.is_a?(Hash) && keys['keys'].is_a?(Array) && keys['keys'].any?

        keys
      end
    end

    def http(verb, url, form = nil)
      uri = URI(url)
      Net::HTTP.start(uri.host, uri.port, use_ssl: uri.scheme == 'https',
                                          open_timeout: TIMEOUT, read_timeout: TIMEOUT) do |h|
        if verb == :post
          h.post(uri.path, URI.encode_www_form(form), 'Content-Type' => 'application/x-www-form-urlencoded')
        else
          h.get(uri.request_uri)
        end
      end
    end
  end
end
