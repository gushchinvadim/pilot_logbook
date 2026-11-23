"""Retire only the old SIM Training site; retain its database/files/certificate."""
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time

SITE = Path('/etc/nginx/sites-available/pilot_logbook')
ENABLED = Path('/etc/nginx/sites-enabled/pilot_logbook')
BACKUPS = Path('/var/backups/pilot-logbook-redirect')


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def write_config(content):
    temporary = SITE.with_name('.pilot_logbook.redirecting')
    with temporary.open('wb') as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    temporary.chmod(0o644)
    os.replace(temporary, SITE)


def apply(stage):
    if socket.gethostname().split('.')[0] != 'cv4666343':
        raise RuntimeError('Это не старый VPS SIM Training. Изменения отменены.')
    if not SITE.is_file() or SITE.is_symlink() or ENABLED.resolve() != SITE.resolve():
        raise RuntimeError('Не найдена ожидаемая конфигурация старого сайта.')
    original = SITE.read_bytes()
    names = {name.replace('\\.', '.') for row in re.findall(r'^\s*server_name\s+([^;]+);', original.decode(), re.M) for name in row.split()}
    if not names or not names.issubset({'survey-ebt.ru', 'www.survey-ebt.ru', '79.174.84.190'}):
        raise RuntimeError('Конфигурация содержит другие сайты. Нужна ручная проверка.')
    new_status = run('curl', '--silent', '--show-error', '--max-time', '15', '--output', '/dev/null', '--write-out', '%{http_code}',
        'https://type-rating.survey-ebt.ru/', capture_output=True, text=True).stdout.strip()
    if new_status != '200':
        raise RuntimeError(f'Новый сайт пока не готов: HTTP {new_status}. Старый не изменён.')
    desired = (stage / 'old-site-redirect.conf').read_bytes()
    BACKUPS.mkdir(parents=True, exist_ok=True, mode=0o700)
    BACKUPS.chmod(0o700)
    backup = BACKUPS / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + f'-{os.getpid()}.conf')
    backup.write_bytes(original)
    backup.chmod(0o600)
    was_active = subprocess.run(['systemctl', 'is-active', '--quiet', 'pilot-logbook']).returncode == 0
    was_enabled = subprocess.run(['systemctl', 'is-enabled', '--quiet', 'pilot-logbook']).returncode == 0
    try:
        write_config(desired)
        run('nginx', '-t')
        run('systemctl', 'reload', 'nginx')
        for path in ('/', '/admin/login/'):
            for attempt in range(10):
                response = run('curl', '--silent', '--show-error', '--max-time', '10', '--head',
                    '--resolve', 'survey-ebt.ru:443:127.0.0.1', 'https://survey-ebt.ru' + path,
                    capture_output=True, text=True).stdout
                lines = response.lower().splitlines()
                if lines and re.match(r'^http/\S+\s+301(?:\s|$)', lines[0]) and f'location: https://type-rating.survey-ebt.ru{path}' in lines:
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError('Проверка перенаправления не прошла.')
        run('systemctl', 'disable', '--now', 'pilot-logbook')
    except Exception:
        write_config(original)
        run('nginx', '-t')
        run('systemctl', 'reload', 'nginx')
        if was_enabled: run('systemctl', 'enable', 'pilot-logbook')
        if was_active: run('systemctl', 'start', 'pilot-logbook')
        raise
    print('survey-ebt.ru перенаправляет на type-rating.survey-ebt.ru (301).')
    print('Старый pilot-logbook остановлен и исключён из автозапуска. БД и файлы сохранены.')
    print(f'Предыдущая конфигурация: {backup}')


if __name__ == '__main__':
    try:
        if os.geteuid() != 0 or len(sys.argv) != 2:
            raise RuntimeError('Запускайте ./redirect-old-site.sh на Mac.')
        apply(Path(sys.argv[1]))
    except Exception as error:
        raise SystemExit(f'Перенаправление не выполнено: {error}')
