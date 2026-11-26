# frozen_string_literal: true

# Prints every route as "VERB PATH controller#action", sorted. tests/routes.txt is the reviewed
# snapshot: when a DocuSeal upgrade adds or changes a route, tests/run_pod_tests.sh fails until someone
# has checked that the new endpoint is authorized (or public on purpose) and updated the snapshot.
lines = Rails.application.routes.routes.filter_map do |r|
  next if r.defaults[:controller].blank?

  "#{r.verb.presence || 'ANY'} #{r.path.spec.to_s.sub('(.:format)', '')} #{r.defaults[:controller]}##{r.defaults[:action]}"
end
puts lines.uniq.sort
