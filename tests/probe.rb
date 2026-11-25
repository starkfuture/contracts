# frozen_string_literal: true

# Read back what the API does not return: contracts' own BCC (tests/matrix.py sends one as a member and
# one as an admin). Prints JSON for tests/run_pod_tests.sh.
bccs = Submission.all.map { |s| s.preferences['bcc_completed'].to_s }
puts "PROBE=#{JSON.generate(member_bcc_kept: bccs.count { |b| b.include?('evil.example') },
                            admin_bcc_kept: bccs.count { |b| b == 'archive-sub@stark-test.example' })}"
