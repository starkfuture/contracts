# frozen_string_literal: true

module Stark
  # Who gets a copy of every signed contract is an admin decision. A contract can carry its own BCC
  # (preferences bcc_completed, from the send form or the API), which wins over the template's and
  # the account's. From anyone but an admin it is dropped, so the admin's template or account BCC
  # applies. Sending still works. Only for changes by a signed-in person (Stark::Current.user).
  module SubmissionGuard
    extend ActiveSupport::Concern

    included do
      before_save :stark_drop_bcc
    end

    private

    def stark_drop_bcc
      user = Stark::Current.user or return
      return if user.role == User::ADMIN_ROLE

      preferences.delete('bcc_completed') if preferences.is_a?(Hash)
    end
  end
end
