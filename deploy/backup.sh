#!/usr/bin/env bash
# Run on the OLD server. Authentication uses peer auth or ~/.pgpass, never a password argument.
set -euo pipefail
umask 077
: "${PGDATABASE:?Set PGDATABASE to the existing database name}"
: "${MEDIA_ROOT:?Set MEDIA_ROOT to the existing media directory}"
if [[ $# -ne 1 ]]; then printf 'Usage: %s /absolute/private/backup-directory\n' "$0" >&2; exit 2; fi
[[ "$1" = /* ]] || { printf 'Use an absolute backup path.\n' >&2; exit 2; }
media_path=$(realpath -- "$MEDIA_ROOT")
[[ -d "$media_path" && "$media_path" != / ]] || { printf 'Invalid MEDIA_ROOT.\n' >&2; exit 2; }
destination=$(realpath -m -- "$1")
case "$destination/" in
    "$media_path/"*) printf 'Backup directory must be outside MEDIA_ROOT.\n' >&2; exit 2 ;;
esac
backup_path="$destination/sim-training-$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -m 700 -p -- "$backup_path"
pg_dump --no-password --format=custom --file="$backup_path/database.dump"
# This checks archive readability only; a separate trial restore is still required.
pg_restore --list "$backup_path/database.dump" > "$backup_path/database.toc.txt"
tar -C "$media_path" -czf "$backup_path/media.tar.gz" .
(
    cd "$backup_path"
    sha256sum database.dump media.tar.gz > SHA256SUMS
)
printf 'Backup created: %s\nTrial restoration must be checked before DNS cutover.\n' "$backup_path"
