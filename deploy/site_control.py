"""Root-only, reversible Nginx maintenance switch for exactly one SIM Training site."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys
import tempfile
import time

DOMAIN = 'type-rating.survey-ebt.ru'
SITE = Path('/etc/nginx/sites-available/sim-training')
ENABLED_SITE = Path('/etc/nginx/sites-enabled/sim-training')
STATE = Path('/var/lib/sim-training-maintenance')
PAGE_DIR = Path('/srv/sim-training/maintenance')
BACKUP = STATE / 'live-nginx.conf'
LAST_BACKUP = STATE / 'last-live-nginx.conf'
MARKER = PAGE_DIR / 'enabled'
LOCK = Path('/srv/sim-training/current/.git/sim-training-deploy.lock')
MAINTENANCE_TAG = b'SIM_TRAINING_MAINTENANCE'


def run(*args):
    return subprocess.run(args, check=True)


def atomic_write(path, contents, mode=0o644):
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def locked():
    fd = os.open(LOCK, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        account = pwd.getpwnam('deploy')
        os.fchown(fd, account.pw_uid, account.pw_gid)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Сейчас выполняется деплой или переключение режима. Повторите позже.') from None
        yield
    finally:
        os.close(fd)


def check_site():
    if not SITE.is_file() or SITE.is_symlink() or ENABLED_SITE.resolve() != SITE.resolve():
        raise RuntimeError('Ожидается отдельная включённая конфигурация /etc/nginx/sites-available/sim-training.')
    names = {name for line in re.findall(r'^\s*server_name\s+([^;]+);', SITE.read_text(), re.M) for name in line.split()}
    if names != {DOMAIN}:
        raise RuntimeError('Конфигурация содержит неожиданные домены. Другие сайты изменяться не будут.')


def http_status(path, backend=False):
    command = ['curl', '--silent', '--show-error', '--max-time', '4', '--output', '/dev/null', '--write-out', '%{http_code}']
    if backend:
        command += ['-H', f'Host: {DOMAIN}', '-H', 'X-Forwarded-Proto: https', 'http://127.0.0.1:8010' + path]
    else:
        # Verify the local Nginx instance and certificate, independent of external DNS caches.
        command += ['--resolve', f'{DOMAIN}:443:127.0.0.1', f'https://{DOMAIN}{path}']
    result = subprocess.run(command, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else 'unavailable'


def wait_for_status(paths, expected):
    for attempt in range(10):
        statuses = {path: http_status(path) for path in paths}
        if all(value == expected for value in statuses.values()):
            return
        if attempt < 9:
            time.sleep(1)
    raise RuntimeError(f'Проверка HTTP не прошла: ожидали {expected}, получили {statuses}.')


def replace_config(contents, expected):
    previous = SITE.read_bytes()
    atomic_write(SITE, contents)
    try:
        run('nginx', '-t')
        run('systemctl', 'reload', 'nginx')
        wait_for_status(('/', '/admin/login/', '/api/docs/') if expected == '503' else ('/', '/admin/login/'), expected)
    except Exception:
        atomic_write(SITE, previous)
        try:
            run('nginx', '-t')
            run('systemctl', 'reload', 'nginx')
        except Exception as rollback:
            raise RuntimeError(f'Не удалось применить режим и перечитать предыдущую конфигурацию: {rollback}. Копия: {BACKUP}') from None
        raise


def off(stage):
    check_site()
    desired = (stage / 'maintenance.nginx.conf').read_bytes()
    page = (stage / 'maintenance.html').read_bytes()
    if MAINTENANCE_TAG not in desired or b'<!doctype html>' not in page.lower():
        raise RuntimeError('Не найдены шаблоны страницы технических работ.')
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE.chmod(0o700)
    PAGE_DIR.mkdir(parents=True, exist_ok=True, mode=0o755)
    PAGE_DIR.chmod(0o755)
    current = SITE.read_bytes()
    if BACKUP.exists():
        if current != desired and current != BACKUP.read_bytes():
            raise RuntimeError('Конфигурация изменилась во время технических работ. Копия сохранена; нужна ручная проверка.')
    else:
        if MAINTENANCE_TAG in current:
            raise RuntimeError('Заглушка уже установлена, но резервная конфигурация отсутствует. Нужна ручная проверка.')
        atomic_write(BACKUP, current, 0o600)
    atomic_write(PAGE_DIR / 'index.html', page)
    replace_config(desired, '503')
    atomic_write(MARKER, b'maintenance\n')
    print('SIM Training закрыт на технические работы. Сайт, админка и API возвращают заглушку (HTTP 503).')


def on():
    check_site()
    if not BACKUP.exists():
        if MARKER.exists() or MAINTENANCE_TAG in SITE.read_bytes():
            raise RuntimeError('Не найдена исходная конфигурация. Нужна ручная проверка; файлы не заменены.')
        wait_for_status(('/', '/admin/login/'), '200')
        print('SIM Training уже доступен.')
        return
    run('systemctl', 'start', 'sim-training')
    for attempt in range(10):
        if http_status('/admin/login/', backend=True) == '200':
            break
        time.sleep(1)
    else:
        raise RuntimeError('Django пока не отвечает. Заглушка сохранена; проверьте sim-training и его журнал.')
    replace_config(BACKUP.read_bytes(), '200')
    MARKER.unlink(missing_ok=True)
    os.replace(BACKUP, LAST_BACKUP)
    print('SIM Training включён. Сайт и админка отвечают HTTP 200.')


def status():
    check_site()
    if MAINTENANCE_TAG in SITE.read_bytes():
        print('Режим: технические работы.')
    elif BACKUP.exists() or MARKER.exists():
        print('Режим: переход не завершён. Проверьте результаты ниже; исходная конфигурация сохранена.')
    else:
        print('Режим: обычная работа.')
    for path in ('/', '/admin/login/', '/api/docs/'):
        print(f'{path}: HTTP {http_status(path)}')


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ('off', 'on', 'status'):
        raise RuntimeError('Запускайте ./site.sh off|on|status на Mac.')
    if os.geteuid() != 0:
        raise RuntimeError('Для переключения Nginx нужен sudo.')
    with locked():
        if sys.argv[1] == 'off':
            off(Path(sys.argv[2]))
        elif sys.argv[1] == 'on':
            on()
        else:
            status()


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f'Ошибка: {error}', file=sys.stderr)
        sys.exit(1)
