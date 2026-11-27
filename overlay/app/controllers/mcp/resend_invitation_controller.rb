# frozen_string_literal: true

module Mcp
  # Stark: email a signer their signing link again, as the web "resend" (SubmittersSendEmailController).
  class ResendInvitationController < McpBaseController
    SCHEMA = {
      name: 'resend_invitation',
      title: 'Resend Invitation',
      description: 'Email one signer their signing link again (also sends it the first time when the document ' \
                   'was created with send_email false).',
      inputSchema: {
        type: 'object',
        properties: {
          submitter_id: { type: 'integer', description: 'Signer (submitter) identifier, from get_document' }
        },
        required: %w[submitter_id]
      },
      annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true }
    }.freeze

    def call
      submitter = Submitter.accessible_by(current_ability).find(mcp_params['submitter_id'])

      authorize!(:update, submitter)

      # The email job skips these silently; say so instead.
      return render_tool_error('Signer has already completed') if submitter.completed_at?
      return render_tool_error('Signer has declined') if submitter.declined_at?
      return render_tool_error('Document has been archived') if submitter.submission.archived_at?
      return render_tool_error('Document has expired') if submitter.submission.expired?
      return render_tool_error('Template has been archived') if submitter.template&.archived_at?
      return render_tool_error('Signer has no email') if submitter.email.blank?

      SendSubmitterInvitationEmailJob.perform_async('submitter_id' => submitter.id)

      submitter.sent_at ||= Time.current
      submitter.save!

      render_tool_result(id: submitter.id, email: submitter.email, sent_at: submitter.sent_at)
    end
  end
end
