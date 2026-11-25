# frozen_string_literal: true

module Stark
  # Who gets a copy of every signed contract is an admin decision. A contract can carry its own BCC
  # (preferences bcc_completed, from the send form or the API), which wins over the template's and
  # the account's. When anyone but an admin sets or changes it, the stored value is put back (none,
  # on a new contract), so the admin's choice applies. Any other save, signing included, leaves it
  # alone. Only for changes by a signed-in person (Stark::Current.user).
  module SubmissionGuard
    extend ActiveSupport::Concern

    included do
      before_save :stark_keep_bcc
    end

    private

    def stark_keep_bcc
      user = Stark::Current.user or return
      return if user.role == User::ADMIN_ROLE || !preferences.is_a?(Hash)

      stored = new_record? ? nil : (attribute_in_database(:preferences) || {})['bcc_completed']
      return if preferences['bcc_completed'].to_s == stored.to_s

      stored.nil? ? preferences.delete('bcc_completed') : preferences['bcc_completed'] = stored
    end
  end
end
