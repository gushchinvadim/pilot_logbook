#!/usr/bin/env bash
# Run on the Mac. Collects configuration only; does not apply security changes.
set -Eeuo pipefail
if [[ $# -gt 0 ]]; then
    printf 'Usage: ./security-check.sh\nRead-only audit of the SIM Training VPS.\n'
    [[ $1 == --help ]] && exit 0
    exit 2
fi
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
TARGET=deploy@129.101.92.158
stamp="$(date -u +%Y%m%dT%H%M%SZ)-$$"
stage="/home/deploy/.cache/sim-training-audit/$stamp"
umask 077
mkdir -p "$ROOT/security-reports"
report="$ROOT/security-reports/vps-$stamp.txt"
ssh -o StrictHostKeyChecking=yes "$TARGET" "umask 077; mkdir -p '$stage'"
scp -o StrictHostKeyChecking=yes "$ROOT/deploy/security_snapshot.sh" "$TARGET:$stage/"
ssh -t -o StrictHostKeyChecking=yes "$TARGET" "bash '$stage/security_snapshot.sh'" | tee "$report"
printf '\nReport saved privately: %s\n' "$report"
