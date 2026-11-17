"""agentrun ps: running sessions grouped by Slurm job, with overlaps, from a mock squeue."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_sessions import LAUNCHER, sessions

TOOLS = LAUNCHER.parent

# Fields follow the --format the caller asks for, so the mock checks that too.
MOCK_SQUEUE = r'''#!/usr/bin/env python3
import json, os, sys
assert "--states=RUNNING" in sys.argv and "--user" in sys.argv
assert "--format=%A|%T|%P|%N|%C|%M|%l|%b|%Z|%j" in sys.argv, sys.argv
for job, j in json.loads(open(os.environ["TEST_SLURM_JOBS"]).read()).items():
    print(f"{job}|RUNNING|gpu|node01|{j['cpus']}|1:00:00|2-00:00:00|{j.get('gres', 'N/A')}|{j['workdir']}|{j['name']}")
'''


class ActiveRunsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="active runs ")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        tools = self.root / "bin"
        tools.mkdir()
        (tools / "squeue").write_text(MOCK_SQUEUE)
        (tools / "squeue").chmod(0o755)
        self.jobs = self.root / "jobs.json"
        self.env = dict(os.environ, HOME=str(self.home), PATH=f"{tools}:{os.environ['PATH']}",
                        TEST_SLURM_JOBS=str(self.jobs))

    def run_dir(self, project, name, agent, job, overlap="", finished=False, register=True, task=""):
        run = self.root / project / ".agent-runs" / name
        run.mkdir(parents=True)
        sessions.init(run, agent, str(self.root / project), "assist")
        (run / "home").mkdir(exist_ok=True)
        (run / "live").mkdir(exist_ok=True)
        (run / "live/slurm_job_id.txt").write_text(job + "\n")
        if task:
            (run / "live/current_task.md").write_text(task + "\n")
        if finished:
            (run / "live/session_finished.txt").write_text("done\n")
        options = [f"--repo={self.root / project}"] + ([f"--overlap-job={overlap}"] if overlap else [])
        subprocess.run(["python3", str(TOOLS / "run_settings.py"), "save", str(run), *options],
                       env=self.env, check=True, capture_output=True)
        if register:
            subprocess.run(["python3", str(TOOLS / "auth_sync.py"), "register", "--store",
                            str(self.home / ".agentrun/auth"), str(run)], env=self.env, check=True, capture_output=True)
        return run

    def ps(self, *args, cwd=None):
        result = subprocess.run([str(LAUNCHER), "ps", *args], cwd=cwd or self.root, env=self.env,
                                capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_runs_are_grouped_by_job_with_overlaps_under_their_host(self):
        self.jobs.write_text(json.dumps({
            "9001": {"cpus": 64, "gres": "gres/gpu:8", "workdir": str(self.root / "main"), "name": "agentrun-assist-claude"},
            "9003": {"cpus": 16, "workdir": str(self.root), "name": "hold-node"},
            "9004": {"cpus": 4, "workdir": str(self.root), "name": "spare"},
        }))
        # The host run is found through its job's working directory, the others through the registry.
        self.run_dir("main", "20261117_090000_assist_claude", "claude", "9001", register=False, task="training baseline")
        self.run_dir("sim a", "20261117_100000_assist_codex", "codex", "9001", overlap="9001")
        self.run_dir("sim b", "20261117_103000_assist_codex", "codex", "9001", overlap="9001", finished=True)
        self.run_dir("old", "20261116_080000_assist_claude", "claude", "8000")
        self.run_dir("sim c", "20261117_110000_assist_claude", "claude", "9003", overlap="9003")
        out = self.ps(cwd=self.home)
        self.assertIn("job 9001  agentrun-assist-claude  partition=gpu  node=node01  CPU=64 GPU=8  経過 1:00:00/2-00:00:00\n", out)
        host = out.index("20261117_090000_assist_claude  claude assist  ジョブ本体")
        overlap = out.index("20261117_100000_assist_codex  codex assist  overlap")
        self.assertLess(host, overlap)
        self.assertIn("作業: training baseline", out)
        self.assertNotIn("20261117_103000", out)   # its session finished
        self.assertNotIn("20261116_080000", out)   # its job is gone
        self.assertIn("job 9003  hold-node  partition=gpu  node=node01  CPU=16  経過 1:00:00/2-00:00:00"
                      "（agentrun 以外で起動したジョブ）", out)
        self.assertIn("└─ 20261117_110000_assist_claude  claude assist  overlap", out)
        self.assertIn("agentrun が動いていない実行中ジョブ", out)
        self.assertIn("  job 9004  spare", out)
        self.assertIn("最終更新", out)

    def test_nothing_running(self):
        self.jobs.write_text("{}")
        self.assertIn("実行中の agentrun はありません。", self.ps())


if __name__ == "__main__":
    unittest.main()
