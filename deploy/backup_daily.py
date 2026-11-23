"""Daily root-owned PostgreSQL/media backups. No Django imports, no service restarts."""
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path('/var/backups/sim-training')
LOCK = Path('/srv/sim-training/current/.git/sim-training-deploy.lock')
ENV_FILE = Path('/etc/sim-training.env')
NAME = re.compile(r'backup-\d{8}T\d{6}Z-\d+$')
KEEP_DAYS = 30
KEEP_MINIMUM = 3
FILES = ('database.dump', 'media.tar.gz', 'environment', 'metadata.json')


def write_private(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def sha256(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def verify(bundle):
    if not NAME.fullmatch(bundle.name) or bundle.is_symlink() or bundle.parent.resolve() != ROOT.resolve():
        raise RuntimeError('Invalid backup location.')
    if not (bundle / 'COMPLETE').is_file():
        raise RuntimeError('Backup has not completed.')
    sums = {}
    for line in (bundle / 'SHA256SUMS').read_text().splitlines():
        checksum, filename = line.split('  ', 1)
        if filename not in FILES or not re.fullmatch(r'[0-9a-f]{64}', checksum) or filename in sums:
            raise RuntimeError('Invalid backup manifest.')
        sums[filename] = checksum
    if set(sums) != set(FILES):
        raise RuntimeError('Incomplete backup manifest.')
    for name in FILES:
        path = bundle / name
        if path.is_symlink() or not path.is_file() or sha256(path) != sums[name]:
            raise RuntimeError(f'Backup checksum failed: {name}')
    with tarfile.open(bundle / 'media.tar.gz', 'r:gz') as archive:
        for member in archive:
            if (member.name.startswith('/') or '..' in Path(member.name).parts
                or ((member.issym() or member.islnk()) and (member.linkname.startswith('/') or '..' in Path(member.linkname).parts))):
                raise RuntimeError('Invalid path in media archive.')
    return json.loads((bundle / 'metadata.json').read_text())


def completed():
    if not ROOT.is_dir():
        return []
    return sorted((p for p in ROOT.iterdir() if NAME.fullmatch(p.name) and p.is_dir()
        and not p.is_symlink() and (p / 'COMPLETE').is_file()), key=lambda p: p.name)


def latest():
    candidates = completed()
    if not candidates:
        raise RuntimeError('No completed SIM Training backups exist.')
    result = candidates[-1]
    verify(result)
    return result


def prune(now):
    bundles = completed()
    cutoff = now - timedelta(days=KEEP_DAYS)
    # Only our complete, dated bundles; keep at least three, and never touch failed attempts/deploy copies.
    for bundle in bundles[:-KEEP_MINIMUM]:
        stamp = datetime.strptime(bundle.name.split('-')[1], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
        if stamp < cutoff:
            shutil.rmtree(bundle)


def create_backup():
    if os.geteuid() != 0:
        raise RuntimeError('Use the installed sim-training-backup service.')
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    ROOT.chmod(0o700)
    media = Path(os.environ['MEDIA_ROOT']).resolve()
    if not media.is_dir() or media == Path('/') or ROOT.resolve().is_relative_to(media):
        raise RuntimeError('Invalid media/backup paths.')
    for name in ('DB_HOST', 'DB_PORT', 'DB_USER', 'DB_PASSWORD', 'DB_NAME'):
        if not os.environ.get(name):
            raise RuntimeError(f'Missing {name}.')
    now = datetime.now(timezone.utc)
    name = f'backup-{now:%Y%m%dT%H%M%SZ}-{os.getpid()}'
    partial = ROOT / ('.' + name + '.partial')
    destination = ROOT / name
    # A read-only fd can take a Linux flock; the backup service never writes the Git directory.
    fd = os.open(LOCK, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        partial.mkdir(mode=0o700)
        env = dict(os.environ, PGHOST=os.environ['DB_HOST'], PGPORT=os.environ['DB_PORT'],
            PGUSER=os.environ['DB_USER'], PGPASSWORD=os.environ['DB_PASSWORD'], PGDATABASE=os.environ['DB_NAME'])
        subprocess.run(['pg_dump', '--no-password', '--format=custom', '--file=' + str(partial / 'database.dump')], env=env, check=True)
        (partial / 'database.dump').chmod(0o600)
        subprocess.run(['pg_restore', '--list', str(partial / 'database.dump')], stdout=subprocess.DEVNULL, check=True)
        with tarfile.open(partial / 'media.tar.gz', 'w:gz', dereference=False) as archive:
            archive.add(media, arcname='.')
        (partial / 'media.tar.gz').chmod(0o600)
        write_private(partial / 'environment', ENV_FILE.read_bytes())
        metadata = {'created_at': now.isoformat(), 'database': os.environ['DB_NAME'], 'database_user': os.environ['DB_USER'],
            'media_root': str(media), 'retention_days': KEEP_DAYS}
        write_private(partial / 'metadata.json', json.dumps(metadata, indent=2).encode())
        write_private(partial / 'SHA256SUMS', ''.join(f'{sha256(partial / f)}  {f}\n' for f in FILES).encode())
        write_private(partial / 'COMPLETE', b'SIM Training backup complete\n')
        os.rename(partial, destination)
        verify(destination)
        prune(now)
    finally:
        os.close(fd)
    print(f'Backup completed: {destination}')
    print('Database snapshot and media archive created without stopping the site.')
    return destination


if __name__ == '__main__':
    try:
        create_backup()
    except Exception as error:
        # No environment or command containing credentials is printed.
        raise SystemExit(f'SIM Training backup failed: {error}')
