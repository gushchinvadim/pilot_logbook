"""Offline deployment orchestration tests. No SSH, sudo, services or real DB are used.
Run: python3 -m unittest discover -s deploy -p test_deploy.py
"""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MOCK_COMMAND = r'''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['TRACE'], 'a') as trace:
    trace.write(json.dumps([name, *args]) + '\n')
if name == 'sudo':
    if args == ['-v']: sys.exit(0)
    if args[:1] == ['-u']: args = args[2:]
    os.execvp(args[0], args)
elif name == 'git':
    if args == ['symbolic-ref', '--short', 'HEAD']: print('main')
    elif args[:2] == ['status', '--porcelain']: print(' M changed.py' if os.environ.get('DIRTY') else '', end='')
    elif args == ['remote', 'get-url', 'origin']: print('git@github.com:gushchinvadim/pilot_logbook.git')
    elif args == ['rev-parse', 'origin/main']: print(('c' if os.environ.get('STALE') else 'a') * 40)
    elif args == ['rev-parse', 'HEAD']: print('b' * 40)
    sys.exit(0)
elif name == 'id': print('deploy')
elif name in ('flock', 'chown', 'systemctl', 'sleep'): pass
elif name == 'chmod':
    sys.exit(subprocess.call(['/bin/chmod', *['750' if arg == '2750' else arg for arg in args]]))
elif name == 'install':
    clean = []
    while args:
        item = args.pop(0)
        if item in ('-o', '-g'): args.pop(0)
        else: clean.append(item)
    sys.exit(subprocess.call(['/usr/bin/install', *clean]))
elif name == 'systemd-run':
    while args and args[0].startswith('--'): args.pop(0)
    env = dict(os.environ, DB_HOST='localhost', DB_PORT='5432', DB_USER='fixture', DB_PASSWORD='fixture', DB_NAME='fixture')
    sys.exit(subprocess.call(args, env=env))
elif name == 'pg_dump':
    destination = next(arg.split('=', 1)[1] for arg in args if arg.startswith('--file='))
    pathlib.Path(destination).write_bytes(b'fixture-backup')
elif name == 'pg_restore': pass
elif name == 'curl': print('503' if os.environ.get('MAINTENANCE') and any(arg.startswith('https://') for arg in args) else '200', end='')
elif name == 'python':
    if os.environ.get('FAIL_MIGRATE') and args[:2] == ['manage.py', 'migrate']: sys.exit(17)
else: sys.exit('Unexpected mock: ' + name)
'''


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sim-deploy-test-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.server = self.root / 'server'
        self.app = self.server / 'current'
        self.web = self.server / 'web'
        self.stage = self.root / 'stage' / ('20261123T000000Z-' + 'a' * 12 + '-123')
        self.bin = self.root / 'bin'
        for folder in (self.app / '.git', self.app / '.venv/bin', self.web, self.stage / 'frontend/assets', self.bin):
            folder.mkdir(parents=True, exist_ok=True)
        (self.web / 'index.html').write_text('old-index')
        (self.stage / 'frontend/index.html').write_text('new-index')
        (self.stage / 'frontend/assets/app.js').write_text('fixture-javascript')
        self.env_file = self.root / 'environment'
        self.env_file.write_text('fixture-only')
        stub = self.bin / 'mock'
        stub.write_text(MOCK_COMMAND)
        stub.chmod(0o755)
        for name in ('sudo', 'git', 'id', 'flock', 'chown', 'chmod', 'install', 'systemctl', 'systemd-run', 'pg_dump', 'pg_restore', 'curl', 'sleep'):
            (self.bin / name).symlink_to(stub)
        (self.app / '.venv/bin/python').symlink_to(stub)
        # Redirect only fixed production paths into the fixture. The orchestration is unchanged.
        source = (ROOT / 'deploy/update_server.sh').read_text()
        source = source.replace('/srv/sim-training', str(self.server)).replace('/etc/sim-training.env', str(self.env_file))
        source = source.replace(r'/home/deploy/\.cache/sim-training-deploy/', re.escape(str(self.root / 'stage')) + '/')
        self.script = self.root / 'update_server.sh'
        self.script.write_text(source)
        self.trace = self.root / 'trace'
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'], TRACE=str(self.trace))

    def run_deploy(self, **flags):
        result = subprocess.run(['bash', str(self.script), 'a' * 40, str(self.stage)], env=dict(self.env, **flags), capture_output=True, text=True)
        self.events = [json.loads(line) for line in self.trace.read_text().splitlines()]
        return result

    def test_success_backs_up_before_migration_and_publishes_frontend(self):
        result = self.run_deploy()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        backup = next(i for i, event in enumerate(self.events) if event[0] == 'pg_dump')
        migration = next(i for i, event in enumerate(self.events) if event[:3] == ['python', 'manage.py', 'migrate'])
        self.assertLess(backup, migration)
        self.assertEqual((self.web / 'index.html').read_text(), 'new-index')
        self.assertEqual((self.web / 'assets/app.js').read_text(), 'fixture-javascript')
        self.assertEqual(self.env_file.read_text(), 'fixture-only')
        self.assertEqual(len(list((self.server / 'shared/backups').glob('*/database.dump'))), 1)
        services = [event for event in self.events if event[0] == 'systemctl']
        self.assertTrue(services)
        self.assertTrue(all('sim-training' in event for event in services))

    def test_migration_failure_does_not_publish_new_index_or_restart(self):
        result = self.run_deploy(FAIL_MIGRATE='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('remains stopped', result.stderr)
        self.assertEqual((self.web / 'index.html').read_text(), 'old-index')
        self.assertNotIn(['systemctl', 'start', 'sim-training'], self.events)

    def test_dirty_server_is_rejected_before_service_stop(self):
        result = self.run_deploy(DIRTY='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(['systemctl', 'stop', 'sim-training'], self.events)
        self.assertEqual((self.web / 'index.html').read_text(), 'old-index')

    def test_different_github_revision_is_rejected_before_service_stop(self):
        result = self.run_deploy(STALE='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('differ', result.stderr)
        self.assertNotIn(['systemctl', 'stop', 'sim-training'], self.events)


    def test_deploy_preserves_maintenance_mode(self):
        marker = self.server / 'maintenance/enabled'
        marker.parent.mkdir()
        marker.write_text('maintenance')
        result = self.run_deploy(MAINTENANCE='1')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(marker.exists())
        self.assertIn('still enabled', result.stdout)
        self.assertEqual((self.web / 'index.html').read_text(), 'new-index')
