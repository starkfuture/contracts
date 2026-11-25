# frozen_string_literal: true

module Stark
  # The signed-in person for the current request (web session, API key or MCP token), for model
  # rules that must hold on every path (Stark::TemplateGuard). Reset after every request by Rails.
  class Current < ActiveSupport::CurrentAttributes
    attribute :user
  end
end
