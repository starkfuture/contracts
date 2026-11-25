# frozen_string_literal: true

# Stark routes, added through DocuSeal's own routes load hook (config/routes.rb ends with
# ActiveSupport.run_load_hooks(:routes, self)), so config/routes.rb stays unpatched.
ActiveSupport.on_load(:routes) do
  patch '/stark/templates/:template_id/visibility', to: 'stark/template_visibility#update',
                                                    as: :stark_template_visibility
end
