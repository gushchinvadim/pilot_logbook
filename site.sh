#!/usr/bin/env bash
# Run on the Mac. Does not require Git commits or a frontend build.
set -Eeuo pipefail
if [[ $# -ne 1 || ! $1 =~ ^(off|on|status)$ ]]; then
    printf 'Usage: ./site.sh off|on|status\n  off: maintenance page for the entire site\n  on: restore public access\n  status: inspect current mode\n'
    [[ ${1:-} == --help ]] && exit 0
    exit 2
fi
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
TARGET=deploy@129.101.92.158
stage="/home/deploy/.cache/sim-training-site/$(date -u +%Y%m%dT%H%M%SZ)-$$"
ssh -o StrictHostKeyChecking=yes "$TARGET" "umask 077; mkdir -p '$stage'"
scp -o StrictHostKeyChecking=yes "$ROOT/deploy/site_control.py" \
    "$ROOT/deploy/maintenance.html" "$ROOT/deploy/maintenance.nginx.conf" "$TARGET:$stage/"
ssh -t -o StrictHostKeyChecking=yes "$TARGET" "sudo python3 '$stage/site_control.py' '$1' '$stage'"
