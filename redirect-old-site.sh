#!/usr/bin/env bash
# Run on the Mac after completing the data comparison.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
TARGET=deploy@79.174.84.190
if [[ $# -ne 0 ]]; then
    printf 'Usage: ./redirect-old-site.sh\nRedirect the old SIM Training domain; keep old DB and files.\n'
    [[ ${1:-} == --help ]] && exit 0
    exit 2
fi
stage="/home/deploy/.cache/sim-training-redirect/$(date -u +%Y%m%dT%H%M%SZ)-$$"
ssh -o StrictHostKeyChecking=yes "$TARGET" "umask 077; mkdir -p '$stage'"
scp -o StrictHostKeyChecking=yes "$ROOT/deploy/old_site_redirect.py" "$ROOT/deploy/old-site-redirect.conf" "$TARGET:$stage/"
ssh -t -o StrictHostKeyChecking=yes "$TARGET" "sudo python3 '$stage/old_site_redirect.py' '$stage'"
