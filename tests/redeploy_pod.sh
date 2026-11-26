#!/bin/bash
# Recreate the throwaway test pod from the current build/app and wait until DocuSeal answers.
# Usage: tests/redeploy_pod.sh <sandbox-namespace>
set -e
NS=$1
K="kubectl --context stark-staging -n $NS"
D=$(cd "$(dirname "$0")/.." && pwd)
$K delete pod docuseal-stark-test --ignore-not-found --wait=true --timeout=90s >/dev/null
python3 "$D/tests/k8s_pod.py" "$NS" | kubectl --context stark-staging apply -f - >/dev/null
if $K wait pod/docuseal-stark-test --for=condition=Ready --timeout=400s >/dev/null 2>&1; then
  echo "ready"
else
  echo "NOT READY"; $K logs docuseal-stark-test 2>&1 | grep -v '^\s*from ' | tail -25; exit 1
fi
