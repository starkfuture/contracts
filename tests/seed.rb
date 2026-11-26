# frozen_string_literal: true

# Seeds a throwaway DocuSeal for tests/matrix.py and prints the cast as JSON (test values only).
# Run inside the test pod: bin/rails runner /tmp/seed.rb
require 'securerandom'

account = Account.first || Account.create!(name: 'Stark Test', timezone: 'UTC', locale: 'en-US')
EncryptedConfig.find_or_create_by!(account:, key: EncryptedConfig::APP_URL_KEY) { |c| c.value = 'http://localhost:3000' }
AccountConfig.find_or_create_by!(account:, key: AccountConfig::ENABLE_MCP_KEY) { |c| c.value = true }

cast = {}
{ 'admin' => 'admin', 'tm' => 'template_manager', 'm1' => 'member', 'm2' => 'member' }.each do |key, role|
  email = "#{key}@stark-test.example"
  password = SecureRandom.base58(20)
  user = account.users.find_or_initialize_by(email:)
  user.assign_attributes(first_name: key, last_name: 'Test', role:, password:)
  user.save!
  mcp = user.mcp_tokens.create!(name: 'matrix')
  cast[key] = { id: user.id, email:, password:, token: user.access_token.token, mcp: mcp.token, role: user.reload.role }
end

def template_for(account, author, name, shared:)
  folder = TemplateFolders.find_or_create_by_name(author, 'Default')
  uuid = SecureRandom.uuid
  account.templates.create!(author:, folder:, name:, stark_shared: shared,
                            submitters: [{ 'name' => 'Signer', 'uuid' => uuid }],
                            fields: [{ 'uuid' => SecureRandom.uuid, 'submitter_uuid' => uuid, 'name' => 'Name',
                                       'type' => 'text', 'required' => false, 'areas' => [] }],
                            schema: [])
end

users = cast.transform_values { |v| User.find(v[:id]) }
templates = {
  't_admin' => template_for(account, users['admin'], 'Admin private', shared: false),
  't_tm' => template_for(account, users['tm'], 'Manager private', shared: false),
  't_m1' => template_for(account, users['m1'], 'Member1 private', shared: false),
  't_shared' => template_for(account, users['admin'], 'Company shared', shared: true)
}

# An archived user: Google sign-in must not let them back in (tests/google.py).
account.users.create!(email: 'archived@stark-test.example', first_name: 'a', last_name: 'a', role: 'member',
                      password: SecureRandom.base58(20), archived_at: Time.current)

# A member created with no role given must be a member (least privilege by default).
default_user = account.users.create!(email: 'default@stark-test.example', first_name: 'd', last_name: 'd',
                                     password: SecureRandom.base58(20))

puts "CAST=#{JSON.generate(users: cast, templates: templates.transform_values(&:id),
                           default_role: default_user.role,
                           stark_shared_column: Template.column_names.include?('stark_shared'))}"
