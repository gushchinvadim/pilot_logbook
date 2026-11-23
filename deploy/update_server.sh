#!/usr/bin/env bash
# Invoked by ../deploy.sh; not a server installer and never copies local database/media/env files.
set -Eeuo pipefail
APP=/srv/sim-training/current
WEB=/srv/sim-training/web
ENV_FILE=/etc/sim-training.env
SERVICE=sim-training
DOMAIN=type-rating.survey-ebt.ru

[[ $# -eq 2 ]] || { printf 'Use ./deploy.sh on the Mac.\n' >&2; exit 2; }
revision=$1
stage=$2
[[ $revision =~ ^[0-9a-f]{40}$ && $stage =~ ^/home/deploy/\.cache/sim-training-deploy/[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}-[0-9]+$ ]] || exit 2
[[ $(id -un) == deploy ]] || { printf 'Run through the deploy SSH account.\n' >&2; exit 2; }
for program in git flock pg_dump pg_restore curl; do command -v "$program" >/dev/null; done
[[ -s "$stage/frontend/index.html" && -d "$stage/frontend/assets" && -x "$APP/.venv/bin/python" ]] || exit 2
cd "$APP"
exec 9>.git/sim-training-deploy.lock
flock -n 9 || { printf 'Another SIM Training deployment is running.\n' >&2; exit 2; }
sudo -v
sudo test -r "$ENV_FILE"
sudo systemctl is-active --quiet "$SERVICE" || { printf 'sim-training is not running. Check it before deploying.\n' >&2; exit 2; }
[[ $(git symbolic-ref --short HEAD) == main && -z $(git status --porcelain --untracked-files=no) ]] || {
    printf 'Server checkout has local changes or is not on main; nothing was overwritten.\n' >&2; exit 2;
}
[[ $(git remote get-url origin) == git@github.com:gushchinvadim/pilot_logbook.git ]] || {
    printf 'Unexpected server Git origin; check it manually.\n' >&2; exit 2;
}
git fetch origin main
[[ $(git rev-parse origin/main) == "$revision" ]] || {
    printf 'Mac main and GitHub main differ. Push your commit or update your Mac, then rerun.\n' >&2; exit 2;
}
previous=$(git rev-parse HEAD)
git merge-base --is-ancestor "$previous" "$revision" || { printf 'Server history diverged; no reset was performed.\n' >&2; exit 2; }
deps_changed=false
if ! git diff --quiet "$previous" "$revision" -- requirements.txt deploy/requirements-production.txt; then deps_changed=true; fi
backup="/srv/sim-training/shared/backups/deploy-$(date -u +%Y%m%dT%H%M%SZ)-${revision:0:12}-$$"
sudo install -d -o simtraining -g simtraining -m 700 /srv/sim-training/shared/backups "$backup"
sudo cp -p "$ENV_FILE" "$backup/environment"
printf '%s\n' "$previous" | sudo tee "$backup/previous-revision" >/dev/null
sudo cp -p "$WEB/index.html" "$backup/index.html"

service_stopped=false
on_error() {
    result=$?
    trap - ERR
    printf '\nDeployment failed (code %s). Backup: %s\n' "$result" "$backup" >&2
    if [[ $service_stopped == true ]]; then
        printf 'SIM Training remains stopped. Check the failed step before restarting; database rollback is not automatic.\n' >&2
    else
        printf 'Check sim-training status and its journal before retrying.\n' >&2
    fi
    exit "$result"
}
trap on_error ERR
manage() {
    sudo systemd-run --quiet --wait --pipe --collect \
        --property=User=simtraining --property=Group=simtraining \
        --property="WorkingDirectory=$APP" --property="EnvironmentFile=$ENV_FILE" \
        --property=UMask=0022 \
        "$APP/.venv/bin/python" manage.py "$@"
}
printf '\nStopping SIM Training and backing up its configured database…\n'
sudo systemctl stop "$SERVICE"
service_stopped=true
sudo systemd-run --quiet --wait --pipe --collect \
    --property=User=simtraining --property=Group=simtraining \
    --property="WorkingDirectory=$APP" --property="EnvironmentFile=$ENV_FILE" \
    --property=UMask=0077 /bin/bash -c '
        set -Eeuo pipefail
        export PGHOST="$DB_HOST" PGPORT="$DB_PORT"
        export PGUSER="$DB_USER" PGPASSWORD="$DB_PASSWORD" PGDATABASE="$DB_NAME"
        exec pg_dump --no-password --format=custom --file="$1"
    ' sim-training-backup "$backup/database.dump"
sudo -u simtraining pg_restore --list "$backup/database.dump" >/dev/null

git merge --ff-only "$revision"
if [[ $deps_changed == true ]]; then
    .venv/bin/python -m pip install -r deploy/requirements-production.txt
fi
manage check --deploy
manage migrate --noinput
manage purge_login_budgets
manage collectstatic --noinput
# Copy hashed assets first; retain previous assets for open browser tabs and the saved index.
for entry in "$stage/frontend/"*; do
    [[ $(basename "$entry") == index.html ]] && continue
    sudo cp -R "$entry" "$WEB/"
done
sudo chown -R deploy:www-data "$WEB"
sudo find "$WEB" -type d -exec chmod 2750 {} +
sudo find "$WEB" -type f -exec chmod 640 {} +
sudo -u www-data test -r "$WEB/assets/$(basename "$(find "$stage/frontend/assets" -type f -name '*.js' -print -quit)")"

if sudo test -f /etc/systemd/system/sim-training.service.d/30-sim-training-security.conf; then
    sudo /usr/bin/python3 deploy/permissions_control.py enforce
fi
sudo systemctl start "$SERVICE"
service_stopped=false
backend_ready=false
for ((attempt=0; attempt<20; attempt++)); do
    code=$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 3 \
        -H "Host: $DOMAIN" -H 'X-Forwarded-Proto: https' http://127.0.0.1:8010/admin/login/ || true)
    if [[ $code == 200 ]] && sudo systemctl is-active --quiet "$SERVICE"; then backend_ready=true; break; fi
    sleep 1
done
[[ $backend_ready == true ]] || { printf 'Django health check failed.\n' >&2; false; }
# Publish index last, atomically, after the matching backend and assets are ready.
sudo install -o deploy -g www-data -m 640 "$stage/frontend/index.html" "$WEB/.index-$revision.html"
sudo mv -f "$WEB/.index-$revision.html" "$WEB/index.html"
expected_http=200
if [[ -f /srv/sim-training/maintenance/enabled ]]; then expected_http=503; fi
for path in / /admin/login/; do
    code=$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' --max-time 15 "https://$DOMAIN$path")
    [[ $code == "$expected_http" ]] || { printf 'HTTPS check failed: %s (%s; expected %s)\n' "$path" "$code" "$expected_http" >&2; false; }
done
if [[ $expected_http == 503 ]]; then
    printf 'Maintenance mode is still enabled. Run ./site.sh on from your Mac when ready.\n'
fi
printf '\nSIM Training deployed: %s\nBackup: %s\n' "$revision" "$backup"
sudo systemctl status "$SERVICE" --no-pager -l
