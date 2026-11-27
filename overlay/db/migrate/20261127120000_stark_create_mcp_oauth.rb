# frozen_string_literal: true

# OAuth for the built-in MCP server (Stark::McpOauth): registered clients and the grants signed in through them.
# Codes and tokens are stored only as sha256.
class StarkCreateMcpOauth < ActiveRecord::Migration[8.1]
  def change
    create_table :stark_mcp_oauth_clients do |t|
      t.string :client_id, null: false, index: { unique: true }
      t.string :client_name
      t.text :redirect_uris, null: false
      t.timestamps
    end

    create_table :stark_mcp_oauth_grants do |t|
      t.references :client, null: false, foreign_key: { to_table: :stark_mcp_oauth_clients, on_delete: :cascade }
      t.references :user, null: false, foreign_key: { on_delete: :cascade }
      t.string :redirect_uri, null: false
      t.string :code_challenge, null: false
      t.string :resource, null: false
      t.string :code_sha256, null: false, index: { unique: true }
      t.datetime :code_expires_at, null: false
      t.datetime :code_used_at
      t.string :access_sha256, index: { unique: true }
      t.datetime :access_expires_at
      t.string :refresh_sha256, index: { unique: true }
      t.string :previous_refresh_sha256, index: { unique: true }
      t.datetime :expires_at, null: false
      t.datetime :revoked_at
      t.timestamps
    end
  end
end
