"""Mac-only backup destination binding and download through an already-open SSD file."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys

PROJECT = Path(__file__).resolve().parents[1]
CONFIG = PROJECT / '.backup-ssd.json'
TARGET = 'deploy@129.101.92.158'


def volume_info(path):
    path = Path(path).expanduser().resolve()
    result = subprocess.run(['diskutil', 'info', '-plist', str(path)], check=True, capture_output=True)
    info = plistlib.loads(result.stdout)
    mount = info.get('MountPoint')
    if not mount or Path(mount).resolve() != path or not os.path.ismount(path):
        raise RuntimeError('Укажите корень подключённого внешнего диска, например /Volumes/MySSD.')
    if info.get('Internal') is not False or not info.get('VolumeUUID'):
        raise RuntimeError('Нужен внешний диск с определяемым UUID. Внутренний диск Mac не используется.')
    if info.get('WritableVolume') is False or info.get('ReadOnlyVolume') is True:
        raise RuntimeError('SSD доступен только для чтения.')
    return path, info


def configure(path):
    mount, info = volume_info(path)
    content = json.dumps({'mount': str(mount), 'uuid': info['VolumeUUID']}, ensure_ascii=False, indent=2).encode()
    fd = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as output:
        output.write(content)
    CONFIG.chmod(0o600)
    print(f'SSD выбран: {mount}. Архивы: {mount / "SIM-Training-backups"}')
    print('Архив содержит персональные данные и настройки доступа. Используйте защищённый/зашифрованный SSD.')


def destination():
    if not CONFIG.is_file():
        raise RuntimeError('Сначала выберите SSD: ./backup.sh target "/Volumes/Имя SSD"')
    saved = json.loads(CONFIG.read_text())
    mount, info = volume_info(saved['mount'])
    if info['VolumeUUID'] != saved['uuid']:
        raise RuntimeError('Под этим именем подключён другой том. Скачивание отменено.')
    return mount


def ssh_cat(path, **kwargs):
    return subprocess.run(['ssh', '-T', '-o', 'StrictHostKeyChecking=yes', TARGET, 'cat', path], check=True, **kwargs)


def download(stage):
    if not re.fullmatch(r'/home/deploy/\.cache/sim-training-backup/\d{8}T\d{6}Z-\d+', stage):
        raise RuntimeError('Неверная папка выгрузки.')
    mount = destination()
    folder = mount / 'SIM-Training-backups'
    if folder.is_symlink():
        raise RuntimeError('Папка резервных копий не должна быть символической ссылкой.')
    folder.mkdir(mode=0o700, exist_ok=True)
    expected = ssh_cat(stage + '/export.sha256', capture_output=True, text=True).stdout.strip()
    if not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise RuntimeError('Неверная контрольная сумма экспорта.')
    # Pin both directory and output file to the actual SSD before starting the stream.
    # An unplug cannot turn the destination into an ordinary folder on the Mac.
    directory_fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    name = f'sim-training-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{os.getpid()}.tar'
    partial = '.' + name + '.partial'
    created = False
    try:
        destination()  # Re-check after preparing the directory.
        fd = os.open(partial, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
        created = True
        with os.fdopen(fd, 'w+b') as output:
            ssh_cat(stage + '/export.tar', stdout=output)
            output.flush()
            os.fsync(output.fileno())
            output.seek(0)
            digest = hashlib.sha256()
            for block in iter(lambda: output.read(1024 * 1024), b''):
                digest.update(block)
            if digest.hexdigest() != expected:
                raise RuntimeError('Контрольная сумма не совпала. Архив не опубликован.')
        destination()
        os.rename(partial, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        created = False
        hash_fd = os.open(name + '.sha256', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
        with os.fdopen(hash_fd, 'w') as output:
            output.write(f'{expected}  {name}\n')
        print(f'Копия сохранена на SSD, SHA-256 проверена: {folder / name}')
    finally:
        if created:
            try: os.unlink(partial, dir_fd=directory_fd)
            except OSError: pass
        os.close(directory_fd)


if __name__ == '__main__':
    try:
        if len(sys.argv) == 3 and sys.argv[1] == 'target': configure(sys.argv[2])
        elif len(sys.argv) == 2 and sys.argv[1] == 'check': print(f'SSD доступен: {destination()}')
        elif len(sys.argv) == 3 and sys.argv[1] == 'download': download(sys.argv[2])
        else: raise RuntimeError('Используйте ./backup.sh target|download|install|run|status|verify')
    except Exception as error:
        raise SystemExit(f'Операция с SSD остановлена: {error}')
