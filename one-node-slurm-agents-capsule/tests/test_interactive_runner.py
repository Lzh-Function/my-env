"""終了済みjobと照会障害を区別する。実際のSlurmには接続しない。"""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('interactive_runner', ROOT / 'runtime/agentrun/interactive-runner.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class SlurmMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        (self.run / 'live').mkdir()
        self.monitor = runner.SlurmMonitor(self.run)

    def job(self):
        self.monitor.job_file.write_text('9001\n')

    def test_pending_start_and_invalid_ids_do_not_query_or_release(self):
        with patch.object(self.monitor, 'query') as query:
            self.assertIsNone(self.monitor.state())
            self.monitor.job_file.write_text('invalid-job-id')
            self.assertIsNone(self.monitor.state())
            query.assert_not_called()

    def test_active_suspended_completing_and_requeued_jobs_are_not_terminal(self):
        self.job()
        for state in ('RUNNING', 'PENDING', 'SUSPENDED', 'COMPLETING', 'REQUEUED',
                      'CONFIGURING', 'TIMEOUT+COMPLETING', 'PREEMPTED'):
            with self.subTest(state=state), patch.object(self.monitor, 'query',
                    return_value=f'JobId=9001 JobState={state}'):
                self.assertIsNone(self.monitor.state())

    def test_terminal_states_are_detected(self):
        self.job()
        for state in runner.TERMINAL:
            with self.subTest(state=state), patch.object(self.monitor, 'query',
                    return_value=f'JobId=9001 JobState={state}'):
                self.assertEqual(self.monitor.state(), state)

    def test_purged_job_requires_two_successful_queue_absences(self):
        self.job()
        with patch.object(self.monitor, 'query', side_effect=[None, '', None, '']):
            self.assertIsNone(self.monitor.state())
            self.assertEqual(self.monitor.state(), 'TERMINATED')

    def test_query_failure_resets_missing_count(self):
        self.job()
        with patch.object(self.monitor, 'query', side_effect=[None, '', None, None,
                                                            None, '', None, '']):
            self.assertIsNone(self.monitor.state())
            self.assertIsNone(self.monitor.state())
            self.assertIsNone(self.monitor.state())
            self.assertEqual(self.monitor.state(), 'TERMINATED')

    def test_queue_fallback_includes_all_states_and_keeps_suspended_job(self):
        self.job()
        with patch.object(self.monitor, 'query', side_effect=[None, '9001|SUSPENDED\n']) as query:
            self.assertIsNone(self.monitor.state())
            args = query.call_args.args[0]
            self.assertIn('--states=all', args)
            self.assertIn(str(os.getuid()), args)

    def test_wrong_control_job_id_is_not_trusted(self):
        self.job()
        with patch.object(self.monitor, 'query', side_effect=['JobId=9002 JobState=TIMEOUT',
                                                            '9001|RUNNING\n']):
            self.assertIsNone(self.monitor.state())

    def test_malformed_queue_output_does_not_count_as_absence(self):
        self.job()
        with patch.object(self.monitor, 'query', side_effect=[None, 'not a job record']):
            self.assertIsNone(self.monitor.state())
            self.assertEqual(self.monitor.missing, 0)

    def test_queries_have_timeout_and_ignore_display_filters(self):
        with patch.dict(os.environ, SQUEUE_PARTITION='unrelated', SQUEUE_STATES='pending'):
            output = self.monitor.query([sys.executable, '-c',
                'import os; print([k for k in os.environ if k.startswith("SQUEUE_")])'])
            self.assertEqual(output, '[]\n')

    def test_missing_command_and_query_timeout_are_not_terminal(self):
        self.assertIsNone(self.monitor.query([str(self.run / 'missing-command')]))
        start = time.monotonic()
        with patch.object(runner, 'QUERY_TIMEOUT', 0.2):
            self.assertIsNone(self.monitor.query([sys.executable, '-c',
                'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)']))
        self.assertLess(time.monotonic() - start, 2)

    def test_query_does_not_wait_for_descendant_output_pipes(self):
        child_pid = self.run / 'query-child.pid'
        script = '''import os, signal, sys, time
pid = os.fork()
if pid:
    open(sys.argv[1], 'w').write(str(pid))
    print('JobId=9001 JobState=RUNNING', flush=True)
else:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(30)
'''
        start = time.monotonic()
        output = self.monitor.query([sys.executable, '-c', script, str(child_pid)])
        self.assertIn('JobState=RUNNING', output)
        self.assertLess(time.monotonic() - start, 2)
        pid = int(child_pid.read_text())
        # 孤児はinitの回収前ならzombieになりうるが、動作中ではない。
        path = Path(f'/proc/{pid}/stat')
        deadline = time.monotonic() + 2
        while path.exists() and ') Z ' not in path.read_text():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)

    def test_cancelled_query_does_not_launch_another_command(self):
        self.monitor.cancelled = lambda: True
        with patch.object(runner.subprocess, 'Popen') as start:
            self.assertIsNone(self.monitor.query(['squeue']))
            start.assert_not_called()

    def test_stop_request_interrupts_an_inflight_query(self):
        start = time.monotonic()
        self.monitor.cancelled = lambda: time.monotonic() - start > 0.2
        self.assertIsNone(self.monitor.query([sys.executable, '-c', 'import time; time.sleep(30)']))
        self.assertLess(time.monotonic() - start, 1)


if __name__ == '__main__':
    unittest.main()
