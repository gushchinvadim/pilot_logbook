#!/usr/bin/env bash
# Run on the Mac. SSD is only required for target/download; server copies are independent.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
TARGET=deploy@129.101.92.158
if [[ ${1:-} == target && $# -eq 2 ]]; then exec python3 "$ROOT/deploy/ssd_backup.py" target "$2"; fi
if [[ $# -ne 1 || ! $1 =~ ^(install|run|status|verify|download)$ ]]; then
    printf 'Usage: ./backup.sh install|run|status|verify|download\n       ./backup.sh target "/Volumes/SSD name"\n'
    [[ ${1:-} == --help ]] && exit 0
    exit 2
fi
action=$1
if [[ $action == download ]]; then python3 "$ROOT/deploy/ssd_backup.py" check; fi
stage="/home/deploy/.cache/sim-training-backup/$(date -u +%Y%m%dT%H%M%SZ)-$$"
ssh -o StrictHostKeyChecking=yes "$TARGET" "umask 077; mkdir -p '$stage'"
scp -o StrictHostKeyChecking=yes "$ROOT/deploy/backup_daily.py" "$ROOT/deploy/backup_admin.py" \
    "$ROOT/deploy/sim-training-backup.service" "$ROOT/deploy/sim-training-backup.timer" "$TARGET:$stage/"
if [[ $action == download ]]; then
    # Only these two temporary export files; permanent server backups are never removed.
    trap 'ssh -o StrictHostKeyChecking=yes "$TARGET" "rm -f -- '\''$stage/export.tar'\'' '\''$stage/export.sha256'\''" || true' EXIT
    ssh -t -o StrictHostKeyChecking=yes "$TARGET" "sudo python3 '$stage/backup_admin.py' export '$stage'"
    python3 "$ROOT/deploy/ssd_backup.py" download "$stage"
else
    ssh -t -o StrictHostKeyChecking=yes "$TARGET" "sudo python3 '$stage/backup_admin.py' '$action' '$stage'"
fi
