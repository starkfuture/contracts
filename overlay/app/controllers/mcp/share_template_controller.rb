# frozen_string_literal: true

module Mcp
  # Stark: share a template with the company or make it private, as Stark::TemplateVisibilityController
  # (update and share: template_manager and admin). Stark::TemplateGuard enforces it on the model too.
  class ShareTemplateController < McpBaseController
    SCHEMA = {
      name: 'share_template',
      title: 'Share Template',
      description: 'Share a template with everyone in the company (shared true) or make it private to its ' \
                   'author again (shared false). Template managers and admins only.',
      inputSchema: {
        type: 'object',
        properties: {
          template_id: { type: 'integer', description: 'Template identifier' },
          shared: { type: 'boolean', description: 'true to share with the company, false to make private' }
        },
        required: %w[template_id shared]
      },
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    }.freeze

    def call
      template = Template.accessible_by(current_ability).find(mcp_params['template_id'])

      authorize!(:update, template)
      authorize!(:share, template)

      return render_tool_error('shared must be true or false') unless mcp_params['shared'].in?([true, false])

      template.update!(stark_shared: mcp_params['shared'])

      render_tool_result(id: template.id, name: template.name, shared: template.stark_shared)
    end
  end
end
