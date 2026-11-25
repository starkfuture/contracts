# frozen_string_literal: true

# Templates are private to their author until a template_manager or admin shares them within the
# company. Existing templates start private: an admin shares the ones everyone should use.
class StarkAddSharedToTemplates < ActiveRecord::Migration[8.1]
  def change
    add_column :templates, :stark_shared, :boolean, null: false, default: false
  end
end
