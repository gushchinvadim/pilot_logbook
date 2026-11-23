#!/usr/bin/env bash
# Run on the Mac, from any directory. Only committed, pushed main is deployed.
set -Eeuo pipefail

PROJECT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SSH_TARGET=deploy@129.101.92.158
APP_DOMAIN=type-rating.survey-ebt.ru
cd "$PROJECT_DIR"

if [[ ${1:-} == --help ]]; then
    printf 'Usage: ./deploy.sh [--dry-run]\nRun on your Mac after committing and pushing main.\n'
    exit 0
fi
if [[ $# -gt 1 || ( $# -eq 1 && $1 != --dry-run ) ]]; then
    printf 'Usage: ./deploy.sh [--dry-run]\n' >&2
    exit 2
fi
for program in git ssh scp yarn; do
    command -v "$program" >/dev/null || { printf 'Missing command: %s\n' "$program" >&2; exit 2; }
done
[[ $(git symbolic-ref --short HEAD) == main ]] || { printf 'Switch to main before deploying.\n' >&2; exit 2; }
revision=$(git rev-parse HEAD)
stage="/home/deploy/.cache/sim-training-deploy/$(date -u +%Y%m%dT%H%M%SZ)-${revision:0:12}-$$"
if [[ ${1:-} == --dry-run ]]; then
    printf 'SIM Training deployment plan\nCommit: %s\nServer: %s\nSite: https://%s\n' "$revision" "$SSH_TARGET" "$APP_DOMAIN"
    printf 'Build frontend locally; upload build; verify GitHub main; back up database; update code/dependencies; migrate; collect static; restart sim-training; publish frontend; check HTTPS.\n'
    printf 'Database settings, media, Nginx configuration and other services are not replaced.\n'
    exit 0
fi

[[ -z $(git status --porcelain) ]] || { printf 'Commit and push all project changes before deploying.\n' >&2; exit 2; }

trap 'printf "Deployment stopped. See the error above; no database is restored automatically.\n" >&2' ERR
printf '\nBuilding SIM Training frontend…\n'
yarn --cwd frontend install --frozen-lockfile
yarn --cwd frontend build
[[ -s frontend/dist/index.html && -d frontend/dist/assets ]] || { printf 'Frontend build is missing.\n' >&2; exit 1; }
# Validate before the remote machine changes anything, including after a build/install.
[[ -z $(git status --porcelain) ]] || { printf 'The build modified tracked files. Review and commit them before deploying.\n' >&2; exit 2; }
printf '\nUploading frontend to %s…\n' "$SSH_TARGET"
ssh -o StrictHostKeyChecking=yes "$SSH_TARGET" "umask 077; mkdir -p '$stage/frontend'"
scp -o StrictHostKeyChecking=yes -r frontend/dist/. "$SSH_TARGET:$stage/frontend/"
scp -o StrictHostKeyChecking=yes deploy/update_server.sh "$SSH_TARGET:$stage/update_server.sh"
# A terminal allows sudo to ask for deploy's password without ever putting it in a command.
ssh -t -o StrictHostKeyChecking=yes "$SSH_TARGET" "bash '$stage/update_server.sh' '$revision' '$stage'"
printf '\nDeployment complete: https://%s/\n' "$APP_DOMAIN"
