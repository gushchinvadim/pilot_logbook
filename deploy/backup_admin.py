"""Root installer/export/restore verification for only SIM Training backups."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys
import tarfile

import backup_daily as backups

LIB = Path('/usr/local/lib/sim-training-backup')
UNITS = Path('/etc/systemd/system')


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def install(stage):
    if not backups.LOCK.is_file() or backups.LOCK.is_symlink():
        raise RuntimeError('Deployment lock missing. Run ./deploy.sh before installing backups.')
    backups.ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    backups.ROOT.chmod(0o700)
    LIB.mkdir(parents=True, exist_ok=True, mode=0o755)
    # Only these new SIM Training files; no other application's timer is replaced.
    for source, target, mode in (
        (stage / 'backup_daily.py', LIB / 'backup_daily.py', 0o755),
        (stage / 'sim-training-backup.service', UNITS / 'sim-training-backup.service', 0o644),
        (stage / 'sim-training-backup.timer', UNITS / 'sim-training-backup.timer', 0o644),
    ):
        temporary = target.with_name('.' + target.name + '.installing')
        with temporary.open('wb') as stream:
            stream.write(source.read_bytes())
        temporary.chmod(mode)
        os.replace(temporary, target)
    run('systemctl', 'daemon-reload')
    run('systemctl', 'enable', '--now', 'sim-training-backup.timer')
    run('systemctl', 'start', 'sim-training-backup.service')
    verify_restore(backups.latest())
    status()


def verify_restore(bundle):
    metadata = backups.verify(bundle)
    name = 'sim_backup_verify_' + datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S') + '_' + str(os.getpid())
    if not re.fullmatch(r'sim_backup_verify_\d{14}_\d+', name):
        raise RuntimeError('Invalid verification database name.')
    created = False
    prefix = ['runuser', '-u', 'postgres', '--']
    try:
        run(*prefix, 'createdb', '--host=/var/run/postgresql', '--owner=' + metadata['database_user'], name, cwd='/tmp')
        created = True
        with (bundle / 'database.dump').open('rb') as source:
            run(*prefix, 'pg_restore', '--host=/var/run/postgresql', '--no-owner', '--no-privileges', '--exit-on-error', '--single-transaction',
                '--role=' + metadata['database_user'], '--dbname=' + name, stdin=source, cwd='/tmp')
        result = run(*prefix, 'psql', '--host=/var/run/postgresql', '-X', '--no-password', '--tuples-only', '--no-align', '--set=ON_ERROR_STOP=1',
            '--dbname=' + name, '--command=' + "SELECT 'users',count(*) FROM auth_user UNION ALL SELECT 'training_sessions',count(*) FROM pilot_training_trainingsession UNION ALL SELECT 'exercise_grades',count(*) FROM pilot_training_ratingexercise;",
            capture_output=True, text=True, cwd='/tmp')
        backups.write_private(bundle / ('RESTORE_VERIFIED-' + str(os.getpid()) + '.txt'), result.stdout.encode())
        print('Trial restore successful in a separate temporary database:')
        print(result.stdout.strip())
    finally:
        if created:
            run(*prefix, 'dropdb', '--host=/var/run/postgresql', name, cwd='/tmp')


def status():
    run('systemctl', 'list-timers', '--all', '--no-pager', 'sim-training-backup.timer')
    run('systemctl', 'show', 'sim-training-backup.service', '--no-pager', '-p', 'Result', '-p', 'ExecMainStatus')
    bundle = backups.latest()
    print(f'Latest verified archive: {bundle.name}')
    print(f'Completed daily archives: {len(backups.completed())}; retention: {backups.KEEP_DAYS} days.')


def export(stage):
    if not re.fullmatch(r'/home/deploy/\.cache/sim-training-backup/\d{8}T\d{6}Z-\d+', str(stage)):
        raise RuntimeError('Invalid private export directory.')
    bundle = backups.latest()
    destination = stage / 'export.tar'
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as output, tarfile.open(fileobj=output, mode='w') as archive:
        archive.add(bundle, arcname=bundle.name)
    digest = backups.sha256(destination)
    backups.write_private(stage / 'export.sha256', (digest + '\n').encode())
    account = pwd.getpwnam('deploy')
    for name in ('export.tar', 'export.sha256'):
        os.chown(stage / name, account.pw_uid, account.pw_gid, follow_symlinks=False)
    print(f'Private export prepared: {bundle.name}')


def main():
    if len(sys.argv) != 3 or os.geteuid() != 0:
        raise RuntimeError('Run ./backup.sh install|run|status|verify|download on the Mac.')
    action, stage = sys.argv[1], Path(sys.argv[2])
    if action == 'install': install(stage)
    elif action == 'run':
        run('systemctl', 'start', 'sim-training-backup.service')
        status()
    elif action == 'status': status()
    elif action == 'verify': verify_restore(backups.latest())
    elif action == 'export': export(stage)
    else: raise RuntimeError('Unknown action.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit(f'SIM Training backup operation failed: {error}')
