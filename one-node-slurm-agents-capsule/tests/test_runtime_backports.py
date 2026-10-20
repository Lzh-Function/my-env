"""Exercise backported fixes through this repository's existing launch scripts."""

import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "runtime/agentrun/agentrun"
FAKE_APPTAINER = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
if sys.argv[1:] == ['--version']:
    print('fake apptainer')
    sys.exit(0)
try:
    os.fstat(200)
except OSError:
    pass
else:
    raise AssertionError('container process inherited repository lock')
args = sys.argv[1:]
assert args[args.index('--no-mount')+1] == 'hostfs,bind-paths,cwd'
for key in ('GH_TOKEN', 'GITHUB_TOKEN', 'APPTAINERENV_GH_TOKEN', 'SINGULARITYENV_GITHUB_TOKEN',
            'APPTAINER_BIND', 'SINGULARITY_BINDPATH'):
    assert key not in os.environ, 'inherited host credential or mount: ' + key
if '/opt/gh-broker/gh.sock' in args:
    import socket, signal
    if os.environ.get('TEST_BROKER_FAILURE'):
        sys.exit(17)
    directory = Path(next(args[i+1].split(':/opt/gh-broker:rw')[0]
                          for i, a in enumerate(args[:-1])
                          if a == '--bind' and args[i+1].endswith(':/opt/gh-broker:rw')))
    Path(os.environ['TEST_BROKER_DIRECTORY']).write_text(str(directory))
    sock = socket.socket(socket.AF_UNIX)
    sock.bind(str(directory / 'gh.sock'))
    while True:
        signal.pause()
Path(os.environ['TEST_CONTAINER_ARGS']).write_text(json.dumps(args))
sys.exit(int(os.environ.get('TEST_CONTAINER_EXIT', '0')))
'''


class RuntimeBackportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='runtime "quotes" with spaces ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'host-home'
        self.home.mkdir()
        binary = self.root / 'bin'
        binary.mkdir()
        apptainer = binary / 'apptainer'
        apptainer.write_text(FAKE_APPTAINER)
        apptainer.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.home), PATH=f"{binary}:{os.environ['PATH']}",
                        AGENTRUN_HISTORY_DIR=str(self.root / "central-history"),
                        TEST_CONTAINER_ARGS=str(self.root / 'container-args.json'),
                        TEST_BROKER_DIRECTORY=str(self.root / 'broker-directory'),
                        SLURM_JOB_ID='9001', SLURM_NTASKS='2', SLURM_NNODES='2')

    def prepare(self, mode='experiment', broker=False):
        if broker:
            token_file = self.home / 'gh.env'
            token_file.write_text('GH_TOKEN=synthetic-broker-only-token\n')
            token_file.chmod(0o600)
            self.env['TEST_GH_ENV_FILE'] = str(token_file)
        args = [str(LAUNCHER), mode, '--agent', 'codex']
        if mode != 'smoke-test':
            args += ['--no-secrets']
            if not broker:
                args += ['--no-gh-broker']
            args += ['fixture']
        if broker:
            # Inject a synthetic gh.env through the existing shell setting.
            args = ['bash', '-c', 'source "$1"; DEFAULT_GH_ENV_FILE="$TEST_GH_ENV_FILE"; main "${@:2}"',
                    'bash', *args]
        result = subprocess.run(args, cwd=self.root, env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return (self.root / '.agent-runs/latest').resolve()

    def execute(self, run, expected=0):
        result = subprocess.run(['bash', str(run / 'submit.sbatch')], cwd=self.root,
                                env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertFalse((run / 'home').exists())
        with (self.root / '.agentrun.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return result

    def test_batch_dns_single_task_and_lock_fd_isolation(self):
        run = self.prepare()
        self.execute(run)
        args = json.loads((self.root / 'container-args.json').read_text())
        for path in ('/etc/resolv.conf', '/etc/hosts'):
            self.assertIn(f'{path}:{path}:ro', args)
        self.assertIn('#SBATCH --nodes=1', (run / 'submit.sbatch').read_text())
        self.assertIn('#SBATCH --ntasks=1', (run / 'submit.sbatch').read_text())
        self.assertEqual((run / 'live/slurm_job_id.txt').read_text(), '9001\n')

    def test_batch_preserves_exit_code_and_excludes_credentials_from_environment_log(self):
        self.env.update(TEST_CONTAINER_EXIT='42', OPENAI_API_KEY='private-test-value',
                        ANTHROPIC_API_KEY='private-test-value', GH_TOKEN='private-test-value',
                        GITHUB_TOKEN='private-test-value', APPTAINERENV_GH_TOKEN='private-test-value',
                        SINGULARITYENV_GITHUB_TOKEN='private-test-value',
                        APPTAINER_BIND='/unintended:/host', SINGULARITY_BINDPATH='/unintended:/host',
                        SLURM_JWT='private-test-value', SLACK_WEBHOOK_URL='private-test-value')
        run = self.prepare()
        self.execute(run, expected=42)
        self.assertEqual((run / 'live/exit_code.txt').read_text(), '42\n')
        log = (run / 'artifacts/environment.txt').read_text()
        self.assertNotIn('private-test-value', log)
        self.assertIn('SLURM_JOB_ID=', log)
        self.assertEqual(json.loads((run / 'live/status.json').read_text())['status'], 'failed')

    def test_batch_rejects_existing_repository_lock_before_starting_container(self):
        run = self.prepare()
        with (self.root / '.agentrun.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = subprocess.run(['bash', str(run / 'submit.sbatch')], cwd=self.root,
                                    env=self.env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('another agentrun', result.stderr)
        self.assertFalse((self.root / 'container-args.json').exists())
        self.assertFalse((run / 'home').exists())

    def test_smoke_script_quotes_slurm_and_shell_paths(self):
        run = self.prepare('smoke-test')
        for line in (run / 'submit.sbatch').read_text().splitlines():
            if line.startswith(('#SBATCH --output=', '#SBATCH --error=')):
                args = shlex.split(line[len('#SBATCH '):])
                self.assertEqual(len(args), 1)
                self.assertIn(str(run), args[0])
        self.execute(run)
        self.assertEqual(json.loads((run / 'artifacts/metrics.json').read_text())['status'], 'passed')

    def test_gh_broker_cleanup_preserves_agent_exit_code(self):
        self.env['TEST_CONTAINER_EXIT'] = '42'
        run = self.prepare(broker=True)
        self.execute(run, expected=42)
        broker = Path((self.root / 'broker-directory').read_text())
        self.assertFalse(broker.exists())
        self.assertNotIn('synthetic-broker-only-token', (run / 'artifacts/environment.txt').read_text())

    def test_failed_broker_stops_before_agent_start(self):
        self.env['TEST_BROKER_FAILURE'] = '1'
        run = self.prepare(broker=True)
        self.execute(run, expected=1)
        self.assertIn('GitHub CLI broker did not start', (run / 'live/stderr.log').read_text())
        self.assertFalse((self.root / 'container-args.json').exists())


if __name__ == '__main__':
    unittest.main()
