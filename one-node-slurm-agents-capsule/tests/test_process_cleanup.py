"""補助processがSIGTERMを無視しても後始末が進むことを確認する。"""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


HELPER = Path(__file__).resolve().parents[1] / 'runtime/agentrun/process-cleanup.sh'


class ProcessCleanupTests(unittest.TestCase):
    def test_term_ignoring_helper_is_killed_without_indefinite_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            ready = Path(directory) / 'ready'
            script = '''source "$1"
"$2" -c 'import os,signal,sys,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); open(sys.argv[1],"w").write(str(os.getpid())); time.sleep(30)' "$3" &
pid=$!
for attempt in {1..100}; do [ ! -f "$3" ] || break; sleep 0.02; done
_agentrun_stop_process "$pid" test-helper
rc=$?
jobs -p > "$3.jobs"
exit "$rc"
'''
            start = time.monotonic()
            result = subprocess.run(['bash', '-c', script, 'bash', str(HELPER), sys.executable,
                str(ready)], capture_output=True, text=True, timeout=8)
            self.assertEqual(result.returncode, 124, result.stdout + result.stderr)
            self.assertLess(time.monotonic() - start, 7)
            self.assertIn('強制停止', result.stderr)
            self.assertEqual(Path(str(ready) + '.jobs').read_text(), '')
            pid = int(ready.read_text())
            stat = Path(f'/proc/{pid}/stat')
            # Reaping can race with opening/reading procfs; a process that
            # disappeared is also successfully stopped.
            try:
                state = stat.read_text()
            except (FileNotFoundError, ProcessLookupError):
                state = None
            self.assertTrue(state is None or ') Z ' in state)

    def test_exit_code_of_stopped_helper_is_preserved(self):
        script = '''source "$1"
sleep 30 &
_agentrun_stop_process "$!" test-helper
'''
        result = subprocess.run(['bash', '-c', script, 'bash', str(HELPER)],
            capture_output=True, text=True, timeout=3)
        self.assertEqual(result.returncode, 143, result.stderr)


if __name__ == '__main__':
    unittest.main()
