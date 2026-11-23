#!/usr/bin/env bash
# Configuration inspection only. No package updates, password changes, restarts or scans.
set -uo pipefail
APP=/srv/sim-training/current
DOMAIN=type-rating.survey-ebt.ru
section() { printf '\n### %s\n' "$1"; }
if [[ $(id -un) != deploy ]]; then printf 'Run using ./security-check.sh on the Mac.\n' >&2; exit 2; fi
sudo -v || exit 1
section 'Timestamp and system'
date -u
hostname
uname -r
lsb_release -ds 2>/dev/null || true
if [[ -f /var/run/reboot-required ]]; then printf 'Reboot required: YES\n'; else printf 'Reboot required: no marker\n'; fi
if [[ -x /usr/lib/update-notifier/apt-check ]]; then /usr/lib/update-notifier/apt-check --human-readable 2>&1; fi
section 'Listening sockets (actual processes)'
sudo ss -lntup
section 'Firewall'
if command -v ufw >/dev/null; then sudo ufw status verbose; else printf 'ufw not installed\n'; fi
section 'Effective SSH settings for this connection'
read -r audit_client_ip audit_client_port audit_server_ip audit_server_port <<< "${SSH_CONNECTION:-127.0.0.1 0 127.0.0.1 22}"
for audit_account in root deploy; do
    printf '\nAccount: %s\n' "$audit_account"
    sudo /usr/sbin/sshd -T -C "user=$audit_account,host=$audit_client_ip,addr=$audit_client_ip,laddr=$audit_server_ip,lport=$audit_server_port" |
        awk '/^(permitrootlogin|passwordauthentication|kbdinteractiveauthentication|pubkeyauthentication|permitemptypasswords|maxauthtries|maxstartups|allowusers|allowgroups|x11forwarding|allowtcpforwarding|authenticationmethods|logingracetime) /'
done
section 'Fail2ban'
if command -v fail2ban-client >/dev/null; then sudo fail2ban-client status; sudo fail2ban-client status sshd; else printf 'fail2ban not installed\n'; fi
section 'Service isolation'
systemctl show sim-training --no-pager -p User -p Group -p WorkingDirectory -p UMask -p NoNewPrivileges -p PrivateTmp -p ProtectSystem -p ProtectHome -p ReadWritePaths -p Restart
section 'Paths and permissions (no file contents)'
for audit_path in /srv/sim-training "$APP" "$APP/.git" "$APP/.venv/bin/python" /srv/sim-training/web /srv/sim-training/shared /srv/sim-training/shared/media-live /srv/sim-training/shared/backups /etc/sim-training.env /home/deploy/.ssh /home/deploy/.ssh/sim_training_github /home/deploy/sim-training-secret.env; do
    sudo stat -c '%a %U:%G %n' "$audit_path" 2>/dev/null || true
done
printf '\nCan application user write code or its parent directories?\n'
for audit_path in /srv /srv/sim-training "$APP" "$APP/.git" "$APP/.venv" "$APP/.venv/bin/python"; do
    if sudo -u simtraining test -w "$audit_path"; then printf 'WRITABLE: %s\n' "$audit_path"; else printf 'not writable: %s\n' "$audit_path"; fi
done
section 'Nginx validation and limits (selected directives only)'
sudo nginx -t
sudo nginx -T 2>/dev/null | awk '
    /^# configuration file/ {audit_file=$0}
    /^[[:space:]]*(limit_req_zone|limit_req|limit_conn_zone|limit_conn|ssl_protocols|server_tokens|client_max_body_size)[[:space:]]/ {print audit_file; print}
'
section 'Production Django checks'
sudo systemd-run --quiet --wait --pipe --collect \
    --property=User=simtraining --property=Group=simtraining \
    --property="WorkingDirectory=$APP" --property=EnvironmentFile=/etc/sim-training.env \
    "$APP/.venv/bin/python" manage.py check --deploy
section 'Whitelisted runtime settings and package versions (no secrets)'
sudo systemd-run --quiet --wait --pipe --collect \
    --property=User=simtraining --property=Group=simtraining \
    --property="WorkingDirectory=$APP" --property=EnvironmentFile=/etc/sim-training.env \
    "$APP/.venv/bin/python" manage.py shell --verbosity 0 -c '
import json
from importlib.metadata import version, PackageNotFoundError
from django.conf import settings
keys = ("DEBUG", "ALLOWED_HOSTS", "CSRF_TRUSTED_ORIGINS", "CORS_ALLOW_ALL_ORIGINS", "CORS_ALLOWED_ORIGINS", "SECURE_SSL_REDIRECT", "SECURE_PROXY_SSL_HEADER", "SESSION_COOKIE_SECURE", "SESSION_COOKIE_HTTPONLY", "SESSION_COOKIE_SAMESITE", "CSRF_COOKIE_SECURE", "X_FRAME_OPTIONS", "SECURE_HSTS_SECONDS", "REST_FRAMEWORK", "MEDIA_ROOT", "STATIC_ROOT")
print(json.dumps({key: getattr(settings, key, None) for key in keys}, ensure_ascii=False, indent=2, default=str))
print("SECRET_KEY_LENGTH_OK:", len(settings.SECRET_KEY) >= 50)
print("DATABASE_ENGINE:", settings.DATABASES["default"]["ENGINE"])
print("DATABASE_HOST:", settings.DATABASES["default"].get("HOST"))
print("DATABASE_NAME:", settings.DATABASES["default"]["NAME"])
for package in ("Django", "djangorestframework", "gunicorn", "sqlparse", "pillow", "openpyxl", "psycopg2-binary"):
    try: print(package, version(package))
    except PackageNotFoundError: print(package, "not installed")
'
section 'Database role and authentication rules'
sudo -u postgres psql -X -d postgres --no-password -c "SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname='sim_training'; SHOW listen_addresses; SELECT type,database,user_name,address,auth_method FROM pg_hba_file_rules;"
section 'Timers and backup presence'
systemctl list-timers --all --no-pager
sudo find /srv/sim-training/shared/backups -maxdepth 2 -type f -name database.dump -printf '%TY-%Tm-%Td %TH:%TM %s bytes %m %p\n' 2>/dev/null || true
section 'Unauthenticated HTTPS responses (no cookies or response bodies)'
for audit_path in / /admin/login/ /api/auth/me/ /api/docs/ /api/my-training-sessions/ /.env /.git/config; do
    printf '\n%s\n' "$audit_path"
    curl --silent --show-error --head --max-time 10 --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN$audit_path" |
        awk 'BEGIN{IGNORECASE=1} /^(HTTP\/|content-type:|strict-transport-security:|x-frame-options:|x-content-type-options:|content-security-policy:|referrer-policy:|server:|cache-control:|retry-after:|x-sim-maintenance:)/'
done
section 'Result'
printf 'Collection completed. Settings, services, database records and firewall rules were not changed.\n'
printf 'A missing section or command error means that check is incomplete, not that the server is secure.\n'
