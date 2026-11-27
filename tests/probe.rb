# frozen_string_literal: true

# Read back what the API does not return: contracts' own BCC. tests/matrix.py sends one as a member
# and one as an admin; then, acting as a member, an unrelated save (as signing does) must keep the
# admin's BCC, and a BCC change must be put back. Prints JSON for tests/run_pod_tests.sh.
bccs = -> { Submission.all.map { |s| s.preferences['bcc_completed'].to_s } }
ours = Account.order(:id).first
admin_sub = Submission.all.find { |s| s.preferences['bcc_completed'] == 'archive-sub@stark-test.example' }
result = { member_bcc_kept: bccs.call.count { |b| b.include?('evil.example') },
           admin_bcc_kept: bccs.call.count { |b| b == 'archive-sub@stark-test.example' } }
if admin_sub
  Stark::Current.user = ours.users.find_by!(role: User::MEMBER_ROLE)
  admin_sub.update!(name: 'touched by a member')
  result[:admin_bcc_survives_member_save] =
    admin_sub.reload.preferences['bcc_completed'] == 'archive-sub@stark-test.example'
  admin_sub.preferences['bcc_completed'] = 'later@evil.example'
  admin_sub.save!
  result[:member_change_put_back] = admin_sub.reload.preferences['bcc_completed'] == 'archive-sub@stark-test.example'
  Stark::Current.reset
end

# Templates shared from a linked account (DocuSeal's testing-account feature, unused at Stark) bypass
# the Stark rules, so only admins may list them. Built in a transaction and rolled back.
ActiveRecord::Base.transaction do
  other = Account.create!(name: 'Linked probe', timezone: 'UTC', locale: 'en-US')
  author = other.users.create!(email: 'linked-probe@example.com', password: SecureRandom.hex(16),
                               first_name: 'L', last_name: 'P', role: User::ADMIN_ROLE)
  AccountLinkedAccount.create!(account: other, linked_account: ours)
  linked = Template.create!(account: other, author:, name: 'Linked probe template', fields: [], schema: [], submitters: [])
  TemplateSharing.create!(template: linked, account_id: ours.id, ability: 'read')
  %w[member template_manager admin].each do |role|
    result[:"linked_shared_#{role}"] = Templates.shared(ours.users.find_by!(role:)).count
  end
  raise ActiveRecord::Rollback
end
sub = Submission.joins(:submitters).first
html = SubmitterMailer.invitation_email(sub.submitters.first).message.body.decoded if sub # single-part HTML mail
result[:stark_email_layout] = html.to_s.include?('Stark Future')
result[:google_new_user_role] = User.find_by(email: 'newbie@stark-test.example')&.role
# The MCP invite_user tool sends upstream's invitation email (tests/matrix.py invites this address).
result[:mcp_invite_email] = EmailEvent.exists?(tag: 'user_invitation', email: 'invited@stark-test.example')
puts "PROBE=#{JSON.generate(result)}"
