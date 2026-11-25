# frozen_string_literal: true

module Stark
  # Shares a template within the company, or makes it private again. Only roles with :share
  # (template_manager, admin) may; members never publish their own templates.
  class TemplateVisibilityController < ApplicationController
    load_and_authorize_resource :template, id_param: :template_id

    def update
      authorize!(:share, @template)

      @template.update!(stark_shared: ActiveModel::Type::Boolean.new.cast(params[:shared]) || false)

      redirect_back fallback_location: template_path(@template),
                    notice: @template.stark_shared? ? 'Shared with the company' : 'Template is now private'
    end
  end
end
