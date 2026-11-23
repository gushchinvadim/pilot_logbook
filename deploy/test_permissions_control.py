"""Offline metadata/rollback tests; never chown real files or run real services."""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import stat
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sim_permissions', ROOT / 'deploy/permissions_control.py')
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


class PermissionHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sim-permissions-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.base = root / 'server'
        self.app = self.base / 'current'
        self.shared = self.base / 'shared'
        for path in (self.app / '.git', self.app / '.venv/bin', self.app / 'deploy', self.shared / 'media-live', self.base / 'maintenance'):
            path.mkdir(parents=True, exist_ok=True)
        self.source = self.app / 'manage.py'
        self.source.write_text('fixture-code')
        self.source.chmod(0o664)
        self.secret_git = self.app / '.git/config'
        self.secret_git.write_text('fixture-git')
        self.external = root / 'outside-python'
        self.external.write_text('outside-not-to-be-modified')
        self.external.chmod(0o755)
        (self.app / '.venv/bin/python').symlink_to(self.external)
        self.config = self.app / 'deploy/gunicorn.conf.py'
        self.config.write_text('control_socket_disable = True\n')
        self.nginx = root / 'sim-nginx.conf'
        self.nginx.write_text('# SIM_TRAINING_MAINTENANCE')
        self.marker = self.base / 'maintenance/enabled'
        self.marker.write_text('maintenance')
        self.dropin = root / 'systemd/security.conf'
        for name, value in {'BASE': self.base, 'APP': self.app, 'SHARED': self.shared,
            'MEDIA': self.shared / 'media-live', 'MARKER': self.marker, 'NGINX': self.nginx,
            'DROP_IN': self.dropin, 'STATE': root / 'snapshots'}.items():
            helper = patch.object(control, name, value)
            helper.start(); self.addCleanup(helper.stop)
        for name, value in [('run', None), ('service_active', True), ('wait_backend', None), ('verify_read_only', None)]:
            helper = patch.object(control, name, return_value=value)
            setattr(self, name, helper.start()); self.addCleanup(helper.stop)
        helper = patch.object(control.os, 'chown')
        self.chown = helper.start(); self.addCleanup(helper.stop)
        helper = patch.object(control.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid()))
        helper.start(); self.addCleanup(helper.stop)
        helper = patch.object(control.grp, 'getgrnam', return_value=SimpleNamespace(gr_gid=os.getgid()))
        helper.start(); self.addCleanup(helper.stop)
        # macOS test filesystem may disallow setgid. The production mode still includes it.
        helper = patch.object(Path, 'chmod', lambda path, mode, **kwargs: os.chmod(path, mode & ~stat.S_ISGID))
        helper.start(); self.addCleanup(helper.stop)

    def test_code_and_git_are_read_only_to_group_without_following_venv_links(self):
        before = self.external.stat().st_mode
        control.enforce_code_permissions()
        self.assertEqual(self.source.read_text(), 'fixture-code')
        self.assertEqual(stat.S_IMODE(self.source.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE(self.secret_git.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.app / '.git').stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.app / '.venv').stat().st_mode), 0o750)
        self.assertEqual(self.external.stat().st_mode, before)
        self.assertEqual(self.external.read_text(), 'outside-not-to-be-modified')
        self.chown.assert_any_call(self.base, 0, 0, follow_symlinks=False)

    def test_apply_saves_manifest_and_installs_strict_service_profile(self):
        control.apply()
        backups = list(control.STATE.glob('*/permissions.json'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(stat.S_IMODE(backups[0].stat().st_mode), 0o600)
        self.assertIn(b'ProtectSystem=strict', self.dropin.read_bytes())
        self.run.assert_any_call('systemctl', 'stop', 'sim-training')
        self.run.assert_any_call('systemctl', 'start', 'sim-training')
        self.assertTrue(self.marker.exists())
        self.assertEqual(self.nginx.read_text(), '# SIM_TRAINING_MAINTENANCE')
        self.assertFalse(any('survey_ebt' in call.args for call in self.run.call_args_list))

    def test_failure_restores_previous_modes_and_service_profile(self):
        self.dropin.parent.mkdir()
        self.dropin.write_bytes(b'previous-profile')
        self.wait_backend.side_effect = RuntimeError('fixture health failure')
        with self.assertRaisesRegex(RuntimeError, 'fixture health'):
            control.apply()
        self.assertEqual(stat.S_IMODE(self.source.stat().st_mode), 0o664)
        self.assertEqual(self.dropin.read_bytes(), b'previous-profile')
        self.assertTrue(self.marker.exists())

    def test_apply_requires_closed_site(self):
        self.marker.unlink()
        with self.assertRaisesRegex(RuntimeError, 'site.sh off'):
            control.apply()
        self.run.assert_not_called()
        self.assertEqual(stat.S_IMODE(self.source.stat().st_mode), 0o664)

    def test_apply_requires_new_gunicorn_config(self):
        self.config.write_text('workers = 2\n')
        with self.assertRaisesRegex(RuntimeError, 'control_socket_disable'):
            control.apply()
        self.run.assert_not_called()

    def test_an_initially_stopped_service_is_not_started(self):
        self.service_active.return_value = False
        control.apply()
        self.wait_backend.assert_not_called()
        self.assertFalse(any(call.args == ('systemctl', 'start', 'sim-training') for call in self.run.call_args_list))

    def test_symlinked_code_root_is_rejected(self):
        alias = self.base / 'symlinked-current'
        alias.symlink_to(self.app, target_is_directory=True)
        with patch.object(control, 'APP', alias), self.assertRaisesRegex(RuntimeError, 'без перенаправления'):
            control.validate_paths()
