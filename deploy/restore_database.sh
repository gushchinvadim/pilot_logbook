#!/usr/bin/env bash
# Run on the NEW server against an explicitly created EMPTY database.
set -euo pipefail
: "${PGDATABASE:?Set PGDATABASE to the NEW empty database name}"
if [[ $# -ne 1 || ! -f "$1" ]]; then printf 'Usage: %s /absolute/path/database.dump\n' "$0" >&2; exit 2; fi
pg_restore --list "$1" > /dev/null
existing=$(psql -X --no-password --set=ON_ERROR_STOP=1 --tuples-only --no-align --command="SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT IN ('pg_catalog','information_schema') AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r','p','v','m','S','f');")
if [[ "$existing" != 0 ]]; then printf 'Refusing to restore: target database is not empty.\n' >&2; exit 3; fi
pg_restore --no-password --no-owner --no-privileges --exit-on-error --single-transaction --dbname="$PGDATABASE" "$1"
printf 'Database restored. Check record counts, then apply application migrations on the NEW server.\n'
