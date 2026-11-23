"""Offline maintenance controller tests; all Nginx/systemd/network calls are mocked."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sim_site_control', ROOT / 'deploy/site_control.py')
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)

LIVE = b'server {\n    server_name type-rating.survey-ebt.ru;\n    location / { proxy_pass http://127.0.0.1:8010; }\n}\n'


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sim-maintenance-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        site = self.root / 'sim-training.conf'
        site.write_bytes(LIVE)
        enabled = self.root / 'enabled-site'
        enabled.symlink_to(site)
        state = self.root / 'state'
        page = self.root / 'page'
        for name, value in {
            'SITE': site, 'ENABLED_SITE': enabled, 'STATE': state, 'PAGE_DIR': page,
            'BACKUP': state / 'live-nginx.conf', 'LAST_BACKUP': state / 'last-live-nginx.conf',
            'MARKER': page / 'enabled',
        }.items():
            patcher = patch.object(control, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.stage = self.root / 'stage'
        self.stage.mkdir()
        for name in ('maintenance.html', 'maintenance.nginx.conf'):
            (self.stage / name).write_bytes((ROOT / 'deploy' / name).read_bytes())
        runner = patch.object(control, 'run')
        self.run = runner.start()
        self.addCleanup(runner.stop)
        waiter = patch.object(control, 'wait_for_status')
        self.wait = waiter.start()
        self.addCleanup(waiter.stop)
        status = patch.object(control, 'http_status', return_value='200')
        self.http = status.start()
        self.addCleanup(status.stop)
        sleeper = patch.object(control.time, 'sleep')
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_off_saves_live_config_only_once_and_closes_entire_site(self):
        control.off(self.stage)
        control.off(self.stage)
        self.assertEqual(control.BACKUP.read_bytes(), LIVE)
        self.assertEqual(control.BACKUP.stat().st_mode & 0o777, 0o600)
        self.assertTrue(control.MARKER.exists())
        self.assertIn('Приносим извинения'.encode(), control.PAGE_DIR.joinpath('index.html').read_bytes())
        self.assertIn(control.MAINTENANCE_TAG, control.SITE.read_bytes())
        self.wait.assert_called_with(('/', '/admin/login/', '/api/docs/'), '503')
        self.assertFalse(any(call.args[:2] == ('systemctl', 'stop') for call in self.run.call_args_list))

    def test_on_restores_exact_original_configuration_and_preserves_copy(self):
        control.off(self.stage)
        control.on()
        self.assertEqual(control.SITE.read_bytes(), LIVE)
        self.assertFalse(control.MARKER.exists())
        self.assertFalse(control.BACKUP.exists())
        self.assertEqual(control.LAST_BACKUP.read_bytes(), LIVE)
        self.run.assert_any_call('systemctl', 'start', 'sim-training')
        self.wait.assert_called_with(('/', '/admin/login/'), '200')
        control.on()  # already on is harmless
        self.assertEqual(control.SITE.read_bytes(), LIVE)

    def test_nginx_validation_failure_restores_previous_configuration(self):
        self.run.side_effect = [subprocess.CalledProcessError(1, 'nginx -t'), None, None]
        with self.assertRaises(subprocess.CalledProcessError):
            control.off(self.stage)
        self.assertEqual(control.SITE.read_bytes(), LIVE)
        self.assertFalse(control.MARKER.exists())
        self.assertEqual(control.BACKUP.read_bytes(), LIVE)

    def test_failed_public_check_rolls_back_configuration(self):
        self.wait.side_effect = RuntimeError('fixture health failure')
        with self.assertRaises(RuntimeError):
            control.off(self.stage)
        self.assertEqual(control.SITE.read_bytes(), LIVE)
        self.assertFalse(control.MARKER.exists())

    def test_backend_failure_does_not_remove_maintenance_page(self):
        control.off(self.stage)
        maintenance = control.SITE.read_bytes()
        self.http.return_value = '503'
        with self.assertRaisesRegex(RuntimeError, 'Django'):
            control.on()
        self.assertEqual(control.SITE.read_bytes(), maintenance)
        self.assertTrue(control.MARKER.exists())
        self.assertEqual(control.BACKUP.read_bytes(), LIVE)

    def test_another_domain_is_rejected_without_changes(self):
        another = LIVE.replace(b'type-rating.survey-ebt.ru', b'other.example')
        control.SITE.write_bytes(another)
        with self.assertRaisesRegex(RuntimeError, 'неожиданные домены'):
            control.off(self.stage)
        self.assertEqual(control.SITE.read_bytes(), another)
        self.run.assert_not_called()

    def test_maintenance_template_has_no_backend_or_static_bypasses(self):
        config = (self.stage / 'maintenance.nginx.conf').read_text()
        self.assertNotIn('proxy_pass', config)
        self.assertEqual(config.count('location / { return 503; }'), 2)
        self.assertIn('/.well-known/acme-challenge/', config)
        self.assertIn('internal;', config)
        self.assertIn('Retry-After', config)
