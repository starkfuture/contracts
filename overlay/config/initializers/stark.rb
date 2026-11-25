# frozen_string_literal: true

# Stark routes, added through DocuSeal's own routes load hook (config/routes.rb ends with
# ActiveSupport.run_load_hooks(:routes, self)), so config/routes.rb stays unpatched.
ActiveSupport.on_load(:routes) do
  patch '/stark/templates/:template_id/visibility', to: 'stark/template_visibility#update',
                                                    as: :stark_template_visibility
end

Rails.application.config.to_prepare do
  # Who is acting, for Stark::TemplateGuard. The three controller bases cover the web app (session),
  # the API (X-Auth-Token) and the built-in MCP server (bearer token); each defines current_user.
  [ApplicationController, Api::ApiBaseController, Mcp::McpBaseController].each do |base|
    base.before_action { Stark::Current.user = current_user }
  end

  Template.include(Stark::TemplateGuard) unless Template < Stark::TemplateGuard
end
