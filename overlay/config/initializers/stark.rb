# frozen_string_literal: true

# Stark routes, added through DocuSeal's own routes load hook (config/routes.rb ends with
# ActiveSupport.run_load_hooks(:routes, self)), so config/routes.rb stays unpatched.
ActiveSupport.on_load(:routes) do
  patch '/stark/templates/:template_id/visibility', to: 'stark/template_visibility#update',
                                                    as: :stark_template_visibility
  # Sign in with Google (Stark::Google). The callback path is the one registered in Google Cloud.
  get '/auth/google', to: 'stark/google_sessions#new', as: :stark_google_sign_in
  get '/identity/connect/oidc-signin', to: 'stark/google_sessions#create', as: :stark_google_callback
  # OAuth for the built-in MCP server (Stark::McpOauthController), served on the public host.
  get '/.well-known/oauth-protected-resource(/mcp)', to: 'stark/mcp_oauth#protected_resource'
  get '/.well-known/oauth-authorization-server', to: 'stark/mcp_oauth#authorization_server'
  post '/oauth/register', to: 'stark/mcp_oauth#register'
  get '/oauth/authorize', to: 'stark/mcp_oauth#authorize'
  get '/oauth/google/callback', to: 'stark/mcp_oauth#callback'
  post '/oauth/consent', to: 'stark/mcp_oauth#consent'
  post '/oauth/token', to: 'stark/mcp_oauth#token'
end

# Authorization codes and PKCE verifiers stay out of every log that filters parameters.
Rails.application.config.filter_parameters += %i[code code_verifier]

Rails.application.config.to_prepare do
  # Who is acting, for Stark::TemplateGuard. The three controller bases cover the web app (session),
  # the API (X-Auth-Token) and the built-in MCP server (bearer token); each defines current_user.
  [ApplicationController, Api::ApiBaseController, Mcp::McpBaseController].each do |base|
    base.before_action { Stark::Current.user = current_user }
  end

  Template.include(Stark::TemplateGuard) unless Template < Stark::TemplateGuard
  Submission.include(Stark::SubmissionGuard) unless Submission < Stark::SubmissionGuard
  User.include(Stark::UserGuard) unless User < Stark::UserGuard
end
