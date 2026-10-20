"""Distinct launches must never reuse a run directory, even in the same second."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

LAUNCHER = Path(__file__).resolve().parents[1] / 'runtime/agentrun/agentrun'


class RunDirectoryTests(unittest.TestCase):
    def test_directory_allocation_error_stops_before_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.agent-runs').write_text('existing non-directory')
            result = subprocess.run([str(LAUNCHER), 'experiment', '--agent', 'codex', '--no-gh-broker', 'fixture'],
                                    cwd=root, env=dict(os.environ, HOME=str(root), AGENTRUN_STATE_DIR=str(root / 'state')),
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('prepared run:', result.stdout)
            self.assertEqual((root / '.agent-runs').read_text(), 'existing non-directory')

    def test_same_timestamp_keeps_prepared_run_contents(self):
        for mode in ('experiment', 'smoke-test'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                home = root / 'host-home'
                home.mkdir()
                script = '''source "$1"
run_id() { printf '20261017_120000_%s_%s\\n' "$1" "$2"; }
if [ "$3" = experiment ]; then
    command_prepare experiment --agent codex --repo "$2" --no-gh-broker first
else
    command_smoke_test --agent codex
fi
first="$(readlink -f .agent-runs/latest)"
printf 'preserved' > "$first/live/sentinel"
cp "$first/prompt.txt" "$2/original-prompt"
if [ "$3" = experiment ]; then
    command_prepare experiment --agent codex --repo "$2" --no-gh-broker second
else
    command_smoke_test --agent codex
fi
printf '%s\\n%s\\n' "$first" "$(readlink -f .agent-runs/latest)" > "$2/paths"
'''
                result = subprocess.run(['bash', '-c', script, 'bash', str(LAUNCHER), str(root), mode],
                                        cwd=root, env=dict(os.environ, HOME=str(home), AGENTRUN_STATE_DIR=str(root / 'state')),
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                first, second = map(Path, (root / 'paths').read_text().splitlines())
                self.assertNotEqual(first, second, 'same-second launches overwrote the previous run')
                self.assertEqual((first / 'prompt.txt').read_text(), (root / 'original-prompt').read_text())
                self.assertEqual((first / 'live/sentinel').read_text(), 'preserved')


if __name__ == '__main__':
    unittest.main()
