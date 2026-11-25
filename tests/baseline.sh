#!/bin/bash
# The same matrix on unmodified DocuSeal (only the Stark migration, so the seed can mark templates
# shared): shows what the fork changes. Usage: tests/baseline.sh <sandbox-namespace>
D=$(cd "$(dirname "$0")/.." && pwd)
B=$(mktemp -d)
trap 'rm -rf "$B"' EXIT
mkdir -p "$B/db/migrate" && cp "$D"/overlay/db/migrate/*.rb "$B/db/migrate/"
APP_DIR="$B" bash "$D/tests/run_pod_tests.sh" "$1"
