# frozen_string_literal: true

# Read back what the API does not return: contracts' own BCC. tests/matrix.py sends one as a member
# and one as an admin; then, acting as a member, an unrelated save (as signing does) must keep the
# admin's BCC, and a BCC change must be put back. Prints JSON for tests/run_pod_tests.sh.
bccs = -> { Submission.all.map { |s| s.preferences['bcc_completed'].to_s } }
admin_sub = Submission.all.find { |s| s.preferences['bcc_completed'] == 'archive-sub@stark-test.example' }
result = { member_bcc_kept: bccs.call.count { |b| b.include?('evil.example') },
           admin_bcc_kept: bccs.call.count { |b| b == 'archive-sub@stark-test.example' } }
if admin_sub
  Stark::Current.user = User.find_by!(role: User::MEMBER_ROLE)
  admin_sub.update!(name: 'touched by a member')
  result[:admin_bcc_survives_member_save] =
    admin_sub.reload.preferences['bcc_completed'] == 'archive-sub@stark-test.example'
  admin_sub.preferences['bcc_completed'] = 'later@evil.example'
  admin_sub.save!
  result[:member_change_put_back] = admin_sub.reload.preferences['bcc_completed'] == 'archive-sub@stark-test.example'
  Stark::Current.reset
end
puts "PROBE=#{JSON.generate(result)}"
