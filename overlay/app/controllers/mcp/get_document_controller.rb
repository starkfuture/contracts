# frozen_string_literal: true

module Mcp
  # Stark: one contract, as the API's GET /submissions/:id shows it, for whoever may read it.
  class GetDocumentController < McpBaseController
    SCHEMA = {
      name: 'get_document',
      title: 'Get Document',
      description: 'Status of one signing request: template, each signer (status, signing URL), and once ' \
                   'everyone signed the signed documents and the audit log as expiring download URLs.',
      inputSchema: {
        type: 'object',
        properties: {
          submission_id: { type: 'integer', description: 'Document (submission) identifier' }
        },
        required: %w[submission_id]
      },
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
    }.freeze

    def call
      submission = Submission.accessible_by(current_ability).find(mcp_params['submission_id'])

      authorize!(:read, submission)

      # Same as Api::SubmissionsController#show: make sure the signed files exist before listing them.
      submitters = submission.submitters.preload(documents_attachments: :blob, attachments_attachments: :blob)
      submitters.each do |submitter|
        if submitter.completed_at? && submitter.documents_attachments.blank?
          submitter.documents_attachments = Submissions::EnsureResultGenerated.call(submitter)
        end
      end
      if submission.audit_trail_attachment.blank? && submission.completed_at?
        submission.audit_trail_attachment = Submissions::EnsureAuditGenerated.call(submission)
      end

      json = Submissions::SerializeForApi.call(submission, submitters, {}, with_events: false, with_values: false)

      render_tool_result(
        id: submission.id,
        name: submission.name,
        template_name: submission.template&.name,
        status: json['status'],
        completed_at: json['completed_at'],
        archived_at: json['archived_at'],
        submitters: json['submitters'].map do |s|
          s.slice('id', 'name', 'email', 'role', 'status', 'completed_at')
           .merge('signing_url' => submit_form_url(slug: s['slug']))
        end,
        documents: json['documents'],
        audit_log_url: json['audit_log_url']
      )
    end
  end
end
