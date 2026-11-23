#!/usr/bin/env bash
set -Eeuo pipefail
if [[ $# -ne 1 || ! $1 =~ ^(check|apply)$ ]]; then
    printf 'Usage: ./secure-permissions.sh check|apply\nApply requires the site to be in maintenance mode and current code already deployed.\n'
    [[ ${1:-} == --help ]] && exit 0
    exit 2
fi
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
TARGET=deploy@129.101.92.158
stage="/home/deploy/.cache/sim-training-permissions/$(date -u +%Y%m%dT%H%M%SZ)-$$"
ssh -o StrictHostKeyChecking=yes "$TARGET" "umask 077; mkdir -p '$stage'"
scp -o StrictHostKeyChecking=yes "$ROOT/deploy/permissions_control.py" "$ROOT/deploy/site_control.py" "$TARGET:$stage/"
ssh -t -o StrictHostKeyChecking=yes "$TARGET" "sudo python3 '$stage/permissions_control.py' '$1'"
