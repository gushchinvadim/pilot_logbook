"""Protect only SIM Training code, with a saved permissions manifest and guarded restart."""
import ast
import json
import os
from pathlib import Path
import pwd
import grp
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone

from site_control import atomic_write, http_status, locked

BASE = Path('/srv/sim-training')
APP = BASE / 'current'
SHARED = BASE / 'shared'
MEDIA = SHARED / 'media-live'
MARKER = BASE / 'maintenance/enabled'
NGINX = Path('/etc/nginx/sites-available/sim-training')
DROP_IN = Path('/etc/systemd/system/sim-training.service.d/30-sim-training-security.conf')
STATE = Path('/var/lib/sim-training-permissions')
PROFILE = b'''# SIM_TRAINING_READ_ONLY_CODE
[Service]
ProtectSystem=strict
ReadWritePaths=
ReadWritePaths=/srv/sim-training/shared/media-live
RuntimeDirectory=sim-training
RuntimeDirectoryMode=0750
CacheDirectory=sim-training
CacheDirectoryMode=0750
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=XDG_CACHE_HOME=/var/cache/sim-training
'''


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def service_active():
    return subprocess.run(['systemctl', 'is-active', '--quiet', 'sim-training']).returncode == 0


def validate_paths():
    for path in (BASE, APP, APP / '.git', APP / '.venv', SHARED, MEDIA):
        if not path.is_dir() or path.is_symlink():
            raise RuntimeError(f'Ожидается обычная папка без перенаправления: {path}')


def nodes():
    yield BASE
    yield SHARED
    for current, directories, files in os.walk(APP, followlinks=False):
        yield Path(current)
        for name in directories:
            path = Path(current) / name
            if path.is_symlink():
                yield path
        for name in files:
            yield Path(current) / name


def manifest():
    result = []
    for path in nodes():
        value = path.lstat()
        result.append({'path': str(path), 'uid': value.st_uid, 'gid': value.st_gid,
            'mode': stat.S_IMODE(value.st_mode), 'symlink': stat.S_ISLNK(value.st_mode)})
    return result


def enforce_code_permissions():
    validate_paths()
    deploy = pwd.getpwnam('deploy')
    app_group = grp.getgrnam('simtraining').gr_gid
    for path in nodes():
        previous = path.lstat()
        if path in (BASE, SHARED):
            os.chown(path, 0, 0, follow_symlinks=False)
            path.chmod(0o755)
            continue
        private_git = path == APP / '.git' or APP / '.git' in path.parents
        os.chown(path, deploy.pw_uid, deploy.pw_gid if private_git else app_group, follow_symlinks=False)
        if stat.S_ISLNK(previous.st_mode):
            # Never follow venv Python links or links to external files.
            continue
        if stat.S_ISDIR(previous.st_mode):
            mode = 0o700 if private_git else 0o2750
        elif stat.S_ISREG(previous.st_mode):
            executable = bool(previous.st_mode & stat.S_IXUSR)
            mode = (0o700 if executable else 0o600) if private_git else (0o750 if executable else 0o640)
        else:
            raise RuntimeError(f'Неожиданный тип файла в папке кода: {path}')
        path.chmod(mode)


def verify_read_only():
    for path in (BASE, APP, APP / '.git', APP / '.venv', APP / '.venv/bin/python'):
        if subprocess.run(['sudo', '-u', 'simtraining', 'test', '-w', str(path)]).returncode == 0:
            raise RuntimeError(f'Пользователь приложения всё ещё может менять код: {path}')
    run('sudo', '-u', 'simtraining', 'test', '-r', str(APP / 'manage.py'))
    run('sudo', '-u', 'simtraining', 'test', '-x', str(APP / '.venv/bin/python'))
    run('sudo', '-u', 'simtraining', 'test', '-w', str(MEDIA))


def wait_backend():
    for _ in range(15):
        if http_status('/admin/login/', backend=True) == '200':
            return
        time.sleep(1)
    raise RuntimeError('Django не ответил после изменения прав.')


def check():
    validate_paths()
    for path in (BASE, APP, APP / '.git', APP / '.venv', MEDIA):
        writable = subprocess.run(['sudo', '-u', 'simtraining', 'test', '-w', str(path)]).returncode == 0
        print(f'{path}: приложение ' + ('МОЖЕТ изменять' if writable else 'не может изменять'))
    print('Профиль systemd:', 'установлен' if DROP_IN.exists() else 'пока не установлен')


def apply():
    validate_paths()
    if not MARKER.exists() or b'SIM_TRAINING_MAINTENANCE' not in NGINX.read_bytes():
        raise RuntimeError('Сначала включите заглушку: ./site.sh off')
    # New Gunicorn must not try writing its default management socket to its old home.
    config = ast.parse((APP / 'deploy/gunicorn.conf.py').read_text())
    disabled = any(isinstance(row, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'control_socket_disable' for target in row.targets)
        and isinstance(row.value, ast.Constant) and row.value.value is True for row in config.body)
    if not disabled:
        raise RuntimeError('Сначала обновите код через ./deploy.sh: требуется control_socket_disable = True.')
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    STATE.chmod(0o700)
    backup = STATE / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + f'-{os.getpid()}')
    backup.mkdir(mode=0o700)
    was_active = service_active()
    previous_dropin = DROP_IN.read_bytes() if DROP_IN.exists() else None
    if was_active:
        run('systemctl', 'stop', 'sim-training')
    entries = []
    try:
        entries = manifest()
        atomic_write(backup / 'permissions.json', json.dumps(entries, ensure_ascii=False, indent=2).encode(), 0o600)
        if previous_dropin is not None:
            atomic_write(backup / 'previous-drop-in.conf', previous_dropin, 0o600)
        enforce_code_permissions()
        DROP_IN.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        atomic_write(DROP_IN, PROFILE)
        run('systemctl', 'daemon-reload')
        verify_read_only()
        if was_active:
            run('systemctl', 'start', 'sim-training')
            wait_backend()
    except Exception:
        run('systemctl', 'stop', 'sim-training')
        # Restore only saved metadata, never file contents, DB, documents or other services.
        for row in entries:
            path = Path(row['path'])
            os.chown(path, row['uid'], row['gid'], follow_symlinks=False)
            if not row['symlink']:
                path.chmod(row['mode'])
        if previous_dropin is None:
            DROP_IN.unlink(missing_ok=True)
        else:
            atomic_write(DROP_IN, previous_dropin)
        run('systemctl', 'daemon-reload')
        if was_active:
            run('systemctl', 'start', 'sim-training')
        print(f'Предыдущие права восстановлены. Снимок: {backup}', file=sys.stderr)
        raise
    print(f'Права SIM Training исправлены. Код доступен приложению только для чтения. Снимок: {backup}')
    print('Заглушка сохранена. SSH, Nginx других сайтов, БД и документы не изменены.')


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ('check', 'apply', 'enforce') or os.geteuid() != 0:
        raise RuntimeError('Запускайте ./secure-permissions.sh check|apply на Mac.')
    if sys.argv[1] == 'enforce':
        # Called by deploy.sh while it holds the shared deployment lock.
        if service_active() or not DROP_IN.exists():
            raise RuntimeError('Enforce доступен только после настройки профиля и при остановленной sim-training.')
        enforce_code_permissions()
        verify_read_only()
        return
    with locked():
        check() if sys.argv[1] == 'check' else apply()


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f'Ошибка: {error}', file=sys.stderr)
        sys.exit(1)
