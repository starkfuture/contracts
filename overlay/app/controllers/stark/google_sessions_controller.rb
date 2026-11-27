# frozen_string_literal: true

module Stark
  # "Sign in with Google". A company Google account signs in as the DocuSeal user with the same email.
  # Someone from the company domain with no DocuSeal user yet gets one, as a member (least privilege;
  # an admin raises the role). Archived or locked users stay out. Password sign-in keeps working.
  # Linking by email is safe because only admins can change a user's email (Stark::UserGuard).
  class GoogleSessionsController < ApplicationController
    skip_before_action :authenticate_user!
    skip_before_action :maybe_redirect_to_setup
    skip_authorization_check

    before_action { head :not_found unless Stark::Google.enabled? }
    # Each callback costs a call to Google. Per network address, so an office behind one address
    # still has room: 30 sign-ins a minute.
    before_action(only: :create) do
      RateLimit.call("stark-google-#{request.remote_ip}", limit: 30, ttl: 1.minute, enabled: true)
    end

    def new
      session[:stark_google] = { 'state' => SecureRandom.urlsafe_base64(32), 'nonce' => SecureRandom.urlsafe_base64(32) }
      redirect_to Stark::Google.authorize_url(redirect_uri:, **session[:stark_google].symbolize_keys),
                  allow_other_host: true
    end

    def create
      expected = session.delete(:stark_google) || {}
      unless expected['state'].present? &&
             ActiveSupport::SecurityUtils.secure_compare(params[:state].to_s, expected['state'])
        return refuse('That sign-in link expired. Please try again.')
      end

      claims = Stark::Google.claims_for(code: params[:code].to_s, redirect_uri:, nonce: expected['nonce'])
      user = Stark::Google.find_or_create_user(claims)
      return refuse('This user cannot sign in (archived or locked). Ask an admin.') unless user.active_for_authentication?

      sign_in(user)
      redirect_to stored_location_for(:user) || root_path
    rescue Stark::Google::Error => e
      Rails.logger.warn("stark google sign-in refused: #{e.message}")
      refuse('Google sign-in failed. Use your company Google account.')
    end

    private

    def redirect_uri
      ENV.fetch('STARK_GOOGLE_REDIRECT_URI', "#{request.base_url}#{Stark::Google::CALLBACK_PATH}")
    end

    def refuse(message)
      redirect_to new_user_session_path, alert: message
    end
  end
end
