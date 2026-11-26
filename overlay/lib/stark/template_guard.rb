# frozen_string_literal: true

module Stark
  # Rules on a template that hold whichever path changes it (web, API, MCP, clone): the model is the
  # one place every path goes through. Only applies to changes made by a signed-in person
  # (Stark::Current.user); jobs and the console are not restricted.
  #
  # - Publishing (public signing link on, or shared/private within the company) needs :share.
  # - Who gets a copy of every signed contract (preferences bcc_completed) is admin-only on an
  #   existing template: it would route other people's contracts to that inbox. A clone keeps the
  #   value of the template it was cloned from (set by an admin).
  # - Permanent delete is admin-only: it destroys every contract made from the template, including
  #   other people's. Archiving stays available to whoever may destroy.
  module TemplateGuard
    extend ActiveSupport::Concern

    included do
      before_save :stark_guard_save
      before_destroy :stark_guard_destroy, prepend: true
    end

    private

    def stark_guard_save
      user = Stark::Current.user or return

      publishing = (will_save_change_to_shared_link? && shared_link?) || will_save_change_to_stark_shared?
      stark_deny!('Only template managers and admins can publish a template.', :share) if
        publishing && !::Ability.new(user).can?(:share, self)

      bcc_was = (attribute_in_database(:preferences) || {})['bcc_completed'].to_s
      stark_deny!('Only admins can change who receives copies of signed contracts.', :update) if
        persisted? && bcc_was != (preferences || {})['bcc_completed'].to_s && user.role != User::ADMIN_ROLE
    end

    def stark_guard_destroy
      user = Stark::Current.user or return

      stark_deny!('Only admins can delete a template permanently.', :destroy) if user.role != User::ADMIN_ROLE
    end

    def stark_deny!(message, action)
      raise CanCan::AccessDenied.new(message, action, self)
    end
  end
end
