#!/bin/bash
# Seed the throwaway pod and run the permission matrix through a port-forward.
# Usage: tests/run_pod_tests.sh <sandbox-namespace>
NS=$1
D=$(cd "$(dirname "$0")/.." && pwd)
K="kubectl --context stark-staging -n $NS"
OUT=$(mktemp -d)
$K cp "$D/tests/seed.rb" docuseal-stark-test:/tmp/seed.rb >/dev/null
$K exec docuseal-stark-test -- sh -c 'cd /app && bin/rails runner /tmp/seed.rb 2>&1' > "$OUT/seed.out"
grep '^CAST=' "$OUT/seed.out" | sed 's/^CAST=//' > "$OUT/cast.json"
[ -s "$OUT/cast.json" ] || { echo "seed failed"; tail -20 "$OUT/seed.out"; exit 1; }
$K port-forward pod/docuseal-stark-test 13000:3000 >/dev/null 2>&1 &
PF=$!
trap 'kill $PF 2>/dev/null; rm -rf "$OUT"' EXIT
for i in $(seq 1 20); do curl -s -o /dev/null http://127.0.0.1:13000/up && break; sleep 1; done
python3 "$D/tests/matrix.py" http://127.0.0.1:13000 "$OUT/cast.json"
MATRIX=$?
$K cp "$D/tests/routes.rb" docuseal-stark-test:/tmp/routes.rb >/dev/null
$K exec docuseal-stark-test -- sh -c 'cd /app && bin/rails runner /tmp/routes.rb 2>/dev/null' > "$OUT/routes.txt"
if diff -u "$D/tests/routes.txt" "$OUT/routes.txt"; then echo "PASS routes: identical to the reviewed snapshot"; ROUTES=0; else echo "FAIL routes: changed, review each new endpoint then update tests/routes.txt"; ROUTES=1; fi
exit $((MATRIX + ROUTES))
