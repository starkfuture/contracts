# frozen_string_literal: true

module Mcp
  # Stark: archive a contract, as the web and API archive do (permission to destroy it). Never deletes.
  class ArchiveDocumentController < McpBaseController
    SCHEMA = {
      name: 'archive_document',
      title: 'Archive Document',
      description: 'Archive a signing request: it leaves the lists and signers can no longer sign. Nothing is deleted.',
      inputSchema: {
        type: 'object',
        properties: {
          submission_id: { type: 'integer', description: 'Document (submission) identifier' }
        },
        required: %w[submission_id]
      },
      annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: true, openWorldHint: false }
    }.freeze

    def call
      submission = Submission.accessible_by(current_ability).find(mcp_params['submission_id'])

      authorize!(:destroy, submission)

      unless submission.archived_at?
        submission.update!(archived_at: Time.current)

        WebhookUrls.enqueue_events(submission, 'submission.archived')
      end

      render_tool_result(id: submission.id, archived_at: submission.archived_at)
    end
  end
end
