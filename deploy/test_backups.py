"""Offline backup/retention/SSD tests. No real PostgreSQL, SSD, SSH or privileged actions."""
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import backup_daily as daily
import backup_admin as manager
import ssd_backup as ssd


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sim-backup-test-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'backups'
        self.media = self.base / 'media'
        self.media.mkdir()
        (self.media / 'manual.pdf').write_bytes(b'%PDF-fixture')
        self.env = self.base / 'environment'
        self.env.write_text('fixture-environment')
        self.lock = self.base / 'lock'
        self.lock.touch()
        for name, value in {'ROOT': self.root, 'LOCK': self.lock, 'ENV_FILE': self.env}.items():
            helper = patch.object(daily, name, value); helper.start(); self.addCleanup(helper.stop)
        helper = patch.object(daily.os, 'geteuid', return_value=0); helper.start(); self.addCleanup(helper.stop)
        helper = patch.dict(os.environ, {'MEDIA_ROOT': str(self.media), 'DB_HOST': '127.0.0.1', 'DB_PORT': '5432',
            'DB_USER': 'fixture', 'DB_PASSWORD': 'fixture', 'DB_NAME': 'fixture'})
        helper.start(); self.addCleanup(helper.stop)
        helper = patch.object(daily.subprocess, 'run', side_effect=self.command)
        self.run = helper.start(); self.addCleanup(helper.stop)

    def command(self, args, **kwargs):
        if args[0] == 'pg_dump':
            path = next(arg.split('=', 1)[1] for arg in args if arg.startswith('--file='))
            Path(path).write_bytes(b'fixture-dump')
        return SimpleNamespace(returncode=0, stdout='')

    def test_completed_backup_has_checksums_and_private_files(self):
        result = daily.create_backup()
        self.assertEqual(daily.latest(), result)
        self.assertEqual(daily.verify(result)['database'], 'fixture')
        self.assertEqual((result / 'environment').read_text(), 'fixture-environment')
        for name in daily.FILES:
            self.assertEqual((result / name).stat().st_mode & 0o777, 0o600)
        self.assertEqual(result.stat().st_mode & 0o777, 0o700)
        dump_call = next(call for call in self.run.call_args_list if call.args[0][0] == 'pg_dump')
        self.assertFalse(any('PASSWORD' in arg or arg == 'fixture' for arg in dump_call.args[0]))

    def test_failed_dump_is_not_a_completed_backup(self):
        self.run.side_effect = RuntimeError('fixture dump failure')
        with self.assertRaises(RuntimeError): daily.create_backup()
        self.assertEqual(daily.completed(), [])
        self.assertTrue(list(self.root.glob('.*.partial')))

    def test_corruption_is_detected(self):
        result = daily.create_backup()
        (result / 'database.dump').write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError, 'checksum'): daily.verify(result)

    def test_retention_only_removes_old_complete_owned_bundles_and_keeps_three(self):
        self.root.mkdir()
        now = datetime.now(timezone.utc)
        for offset in (100, 90, 80, 70, 60):
            bundle = self.root / f'backup-{now-timedelta(days=offset):%Y%m%dT%H%M%SZ}-{offset}'
            bundle.mkdir(); (bundle / 'COMPLETE').touch()
        unrelated = self.root / 'deploy-do-not-touch'
        unrelated.mkdir()
        partial = self.root / '.failed.partial'
        partial.mkdir()
        daily.prune(now)
        self.assertEqual(len(daily.completed()), 3)
        self.assertTrue(unrelated.exists())
        self.assertTrue(partial.exists())

    def test_trial_restore_uses_a_new_db_and_drops_only_that_db(self):
        result = daily.create_backup()
        with patch.object(manager, 'run', return_value=SimpleNamespace(stdout='users|15\n')) as command:
            manager.verify_restore(result)
        create = next(call for call in command.call_args_list if 'createdb' in call.args)
        drop = next(call for call in command.call_args_list if 'dropdb' in call.args)
        self.assertTrue(create.args[-1].startswith('sim_backup_verify_'))
        self.assertEqual(create.args[-1], drop.args[-1])
        self.assertNotEqual(create.args[-1], 'fixture')
        restore = next(call for call in command.call_args_list if 'pg_restore' in call.args)
        self.assertIn('--dbname=' + create.args[-1], restore.args)
        self.assertIn('stdin', restore.kwargs)


class SSDTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sim-ssd-test-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        helper = patch.object(ssd, 'CONFIG', self.root / 'target.json'); helper.start(); self.addCleanup(helper.stop)

    def test_missing_ssd_never_creates_fallback_folder(self):
        ssd.CONFIG.write_text(json.dumps({'mount': '/Volumes/missing-test-ssd', 'uuid': 'fixture'}))
        with patch.object(ssd, 'volume_info', side_effect=RuntimeError('not mounted')):
            with self.assertRaises(RuntimeError): ssd.destination()
        self.assertEqual(list(self.root.iterdir()), [ssd.CONFIG])

    def test_changed_volume_uuid_is_rejected(self):
        ssd.CONFIG.write_text(json.dumps({'mount': '/Volumes/fixture', 'uuid': 'expected'}))
        with patch.object(ssd, 'volume_info', return_value=(Path('/Volumes/fixture'), {'VolumeUUID': 'different'})):
            with self.assertRaisesRegex(RuntimeError, 'другой том'): ssd.destination()

    def test_download_is_published_only_after_checksum_verification(self):
        content = b'fixture exported backup'
        digest = hashlib.sha256(content).hexdigest()
        def cat(path, **kwargs):
            if path.endswith('.sha256'): return SimpleNamespace(stdout=digest)
            kwargs['stdout'].write(content)
            return SimpleNamespace(returncode=0)
        with patch.object(ssd, 'destination', return_value=self.root), patch.object(ssd, 'ssh_cat', side_effect=cat):
            ssd.download('/home/deploy/.cache/sim-training-backup/20261123T000000Z-123')
        archives = list((self.root / 'SIM-Training-backups').glob('*.tar'))
        self.assertEqual(len(archives), 1)
        self.assertEqual(archives[0].read_bytes(), content)
        self.assertTrue(archives[0].with_suffix('.tar.sha256').exists())

    def test_failed_checksum_does_not_publish_archive(self):
        def cat(path, **kwargs):
            if path.endswith('.sha256'): return SimpleNamespace(stdout='0'*64)
            kwargs['stdout'].write(b'changed')
            return SimpleNamespace(returncode=0)
        with patch.object(ssd, 'destination', return_value=self.root), patch.object(ssd, 'ssh_cat', side_effect=cat):
            with self.assertRaisesRegex(RuntimeError, 'Контрольная сумма'):
                ssd.download('/home/deploy/.cache/sim-training-backup/20261123T000000Z-123')
        self.assertEqual(list((self.root / 'SIM-Training-backups').iterdir()), [])
