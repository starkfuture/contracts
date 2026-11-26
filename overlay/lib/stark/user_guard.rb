# frozen_string_literal: true

module Stark
  # Only admins change a user's email. Google sign-in finds people by email; without this a member
  # could rename themselves to a colleague's unused company address (DocuSeal sends no confirmation)
  # and be the account that colleague lands in, with the member still holding its password.
  # Only for changes by a signed-in person (Stark::Current.user); new users and admins are unaffected.
  module UserGuard
    extend ActiveSupport::Concern

    included do
      before_save :stark_guard_email
    end

    private

    def stark_guard_email
      actor = Stark::Current.user or return
      return if new_record? || !will_save_change_to_email? || actor.role == User::ADMIN_ROLE

      raise CanCan::AccessDenied.new('Only admins can change a user\'s email.', :update, self)
    end
  end
end
