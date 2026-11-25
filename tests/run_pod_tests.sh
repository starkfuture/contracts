#!/bin/bash
# Seed the throwaway pod and run the permission matrix through a port-forward.
# Usage: tests/run_pod_tests.sh <sandbox-namespace>   (recreates the pod first)
# APP_DIR=<dir> runs the same suite on other files, e.g. tests/baseline.sh.
NS=$1
D=$(cd "$(dirname "$0")/.." && pwd)
K="kubectl --context stark-staging -n $NS"
OUT=$(mktemp -d)
bash "$D/tests/redeploy_pod.sh" "$NS" || exit 1   # a fresh pod: the seed is not re-runnable
$K cp "$D/tests/seed.rb" docuseal-stark-test:/tmp/seed.rb >/dev/null
$K exec docuseal-stark-test -- sh -c 'cd /app && bin/rails runner /tmp/seed.rb 2>&1' > "$OUT/seed.out"
grep '^CAST=' "$OUT/seed.out" | sed 's/^CAST=//' > "$OUT/cast.json"
[ -s "$OUT/cast.json" ] || { echo "seed failed"; tail -20 "$OUT/seed.out"; exit 1; }
PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
$K port-forward pod/docuseal-stark-test "$PORT:3000" >/dev/null 2>&1 &
PF=$!
trap 'kill $PF 2>/dev/null; rm -rf "$OUT"' EXIT
for i in $(seq 1 30); do curl -s -o /dev/null "http://127.0.0.1:$PORT/up" && break; sleep 1; done
curl -s -o /dev/null "http://127.0.0.1:$PORT/up" || { echo "port-forward never answered"; exit 1; }
python3 "$D/tests/matrix.py" "http://127.0.0.1:$PORT" "$OUT/cast.json"
MATRIX=$?
$K cp "$D/tests/routes.rb" docuseal-stark-test:/tmp/routes.rb >/dev/null
$K exec docuseal-stark-test -- sh -c 'cd /app && bin/rails runner /tmp/routes.rb 2>/dev/null' > "$OUT/routes.txt"
if diff -u "$D/tests/routes.txt" "$OUT/routes.txt"; then echo "PASS routes: identical to the reviewed snapshot"; ROUTES=0; else echo "FAIL routes: changed, review each new endpoint then update tests/routes.txt"; ROUTES=1; fi
exit $((MATRIX + ROUTES))
