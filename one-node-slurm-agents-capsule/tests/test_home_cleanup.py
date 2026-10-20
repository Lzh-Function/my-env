"""NFS-like transient busy files must not leave home or delete saved history."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


HELPER = Path(__file__).resolve().parents[1] / 'runtime/agentrun/process-cleanup.sh'


class HomeCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='home cleanup with spaces ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / 'run'
        (self.run / 'home').mkdir(parents=True)
        (self.run / 'live').mkdir()
        (self.run / 'home/auth.json').write_text('synthetic private auth')
        self.history = self.root / '.sessions/original/.codex/sessions'
        self.history.mkdir(parents=True)
        (self.history / 'conversation.jsonl').write_text('saved conversation')
        (self.run / 'home/sessions').symlink_to(self.history, target_is_directory=True)

    def cleanup(self, env=None):
        return subprocess.run(['bash', '-c', 'source "$1"; _agentrun_cleanup_home "$2"',
            'bash', str(HELPER), str(self.run)], env=env, text=True,
            capture_output=True, timeout=5)

    def busy_rm(self, failures):
        binary = self.root / 'bin'
        binary.mkdir()
        mock = binary / 'rm'
        mock.write_text(f'''#!{sys.executable}
import os, sys
from pathlib import Path
count = Path({str(self.root / 'attempts')!r})
attempt = int(count.read_text()) + 1 if count.exists() else 1
count.write_text(str(attempt))
if attempt <= {failures}:
    print('cannot remove .nfs-test: Device or resource busy', file=sys.stderr)
    sys.exit(1)
os.execv({shutil.which('rm')!r}, ['rm', *sys.argv[1:]])
''')
        mock.chmod(0o755)
        return dict(os.environ, PATH=f'{binary}:{os.environ["PATH"]}')

    def assert_history(self):
        self.assertEqual((self.history / 'conversation.jsonl').read_text(), 'saved conversation')

    def test_removes_home_without_following_session_symlinks(self):
        result = self.cleanup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.run / 'home').exists())
        self.assert_history()
        self.assertEqual(self.cleanup().returncode, 0)  # already removed

    def test_retries_busy_files_and_preserves_diagnostics(self):
        result = self.cleanup(self.busy_rm(2))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.run / 'home').exists())
        self.assertEqual((self.root / 'attempts').read_text(), '3')
        self.assertIn('Device or resource busy', (self.run / 'live/home_cleanup.log').read_text())
        self.assert_history()

    def test_permanently_busy_home_is_reported_after_finite_retries(self):
        env = self.busy_rm(100)
        start = time.monotonic()
        result = self.cleanup(env)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertLess(time.monotonic() - start, 4)
        self.assertEqual((self.root / 'attempts').read_text(), '5')
        self.assertTrue((self.run / 'home/auth.json').exists())
        log = (self.run / 'live/home_cleanup.log').read_text()
        self.assertIn('attempt 5 failed', log)
        self.assertNotIn('synthetic private auth', log)
        self.assert_history()


if __name__ == '__main__':
    unittest.main()
