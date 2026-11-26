"""確保ジョブ（agentrun hold）を mock Slurm で検証する。"""

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import unittest
from unittest import mock

from test_overlap import JOB, LAUNCHER, OverlapBase
from test_sessions import sessions

sys.path.insert(0, str(LAUNCHER.parent))
import history  # noqa: E402

HOLD = "7001"
HELPER = LAUNCHER.with_name("hold.py")

MOCK_SINFO = r'''#!/usr/bin/env python3
import sys
args = " ".join(sys.argv[1:])
if "--format=%P" in args:
    print("gpu*")
    print("small")
elif "--Node" in args:
    print("node01|64|512000|gpu:a100:4(S:0-1)")
elif "--format=%l" in args:
    print("7-00:00:00")
'''

# Records the submission and makes the new hold job visible to squeue as running.
MOCK_SBATCH = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
Path(os.environ["TEST_SBATCH_LOG"]).write_text(json.dumps(sys.argv[1:]))
path = Path(os.environ["TEST_SLURM_JOBS"])
jobs = json.loads(path.read_text())
folder = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--chdir="))
jobs["7777"] = {"name": "agentrun-hold", "state": "RUNNING", "partition": "gpu", "cpus": 64, "workdir": folder}
path.write_text(json.dumps(jobs))
print("7777")
'''

MOCK_SCANCEL = r'''#!/usr/bin/env python3
import os, sys
with open(os.environ["TEST_SCANCEL_LOG"], "a") as log:
    log.write(" ".join(sys.argv[1:]) + "\n")
'''


class HoldBase(OverlapBase):
    def setUp(self):
        super().setUp()
        for name, text in (("sinfo", MOCK_SINFO), ("sbatch", MOCK_SBATCH), ("scancel", MOCK_SCANCEL)):
            path = self.bin / name
            path.write_text(text)
            path.chmod(0o755)
        self.sbatch_log = self.root / "sbatch.json"
        self.scancel_log = self.root / "scancel.log"
        self.env.update(TEST_SBATCH_LOG=str(self.sbatch_log), TEST_SCANCEL_LOG=str(self.scancel_log))
        self.folder = self.root / "hold folder"
        for sub in ("queue", "started"):
            (self.folder / sub).mkdir(parents=True)

    def hold_job(self, state="RUNNING", **extra):
        self.set_jobs({HOLD: {"name": "agentrun-hold", "state": state, "partition": "gpu", "cpus": 8,
                              "workdir": str(self.folder), "tres": "AllocTRES=cpu=8,gres/gpu=2", **extra}})

    def make_run(self, name, agent="codex"):
        run = self.root / ".agent-runs" / name
        sessions.init(run, agent, str(self.second), "assist")
        (run / "live").mkdir(exist_ok=True)
        (run / "home").mkdir(exist_ok=True)
        return run

    def hold(self, *args, expected=0):
        result = subprocess.run(["python3", str(HELPER), *map(str, args)], capture_output=True, text=True,
                                env=self.env, cwd=self.root, timeout=20)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result


class HoldStartTests(HoldBase):
    def test_start_takes_the_whole_node_for_the_partition_limit_or_the_given_time(self):
        output = self.launcher("hold", "start", "--no-wait").stdout
        self.assertIn("確保ジョブを投入しました: job 7777（partition=gpu、CPU 64、メモリ全部、GPU 4、制限時間 7-00:00:00）",
                      output)
        args = json.loads(self.sbatch_log.read_text())
        folder = Path(next(a.split("=", 1)[1] for a in args if a.startswith("--chdir=")))
        self.assertEqual(folder.parent, self.root / ".agent-runs/.hold")
        script = (folder / "hold.sbatch").read_text()
        for line in ("#SBATCH --job-name=agentrun-hold", "#SBATCH --partition=gpu", "#SBATCH --cpus-per-task=64",
                     "#SBATCH --mem=0", "#SBATCH --exclusive", "#SBATCH --gres=gpu:4", "#SBATCH --time=7-00:00:00"):
            self.assertIn(line + "\n", script)
        self.assertIn(f"--output={folder}/hold.out", args)  # paths with spaces stay off #SBATCH lines
        self.assertIn(f"hold.py' dispatch '{folder}'", script)
        self.assertTrue((folder / "queue").is_dir())
        self.assertEqual(json.loads((folder / "hold.json").read_text())["job"], "7777")
        # One hold job per partition; another time limit for another partition.
        self.assertIn("パーティション gpu には確保ジョブがあります",
                      self.launcher("hold", "start", "--no-wait", expected=2).stderr)
        self.launcher("hold", "start", "--partition", "small", "--time", "1-00:00:00", "--no-wait")
        args = json.loads(self.sbatch_log.read_text())
        script = (Path(next(a.split("=", 1)[1] for a in args if a.startswith("--chdir="))) / "hold.sbatch").read_text()
        self.assertIn("#SBATCH --partition=small\n", script)
        self.assertIn("#SBATCH --time=1-00:00:00\n", script)

    def test_start_waits_until_the_job_runs(self):
        output = self.launcher("hold", "start").stdout
        self.assertIn("確保ジョブ 7777 が動き始めました", output)

    def test_status_and_stop_list_the_sessions_in_it(self):
        self.hold_job()
        run = self.make_run("20261126_100000_assist_codex")
        (run / "live/slurm_job_id.txt").write_text(HOLD + "\n")
        (run / "live/slurm_step_id.txt").write_text("3\n")
        output = self.launcher("hold", "status").stdout
        self.assertIn(f"job {HOLD}  partition=gpu  CPU 8 / GPU 2  経過 10:00 / 上限 2:00:00（残り 1:50:00）", output)
        self.assertIn(f"{run.name}  codex assist  対話  step 3", output)
        self.assertIn("--yes を付けてください", self.launcher("hold", "stop", expected=2).stderr)
        self.launcher("hold", "stop", "--yes")
        self.assertEqual(self.scancel_log.read_text(), f"{HOLD}\n")


class HoldLaunchTests(HoldBase):
    def test_interactive_sessions_join_the_hold_job_unless_no_hold(self):
        self.hold_job()
        rc, output = self.execute(["assist", "--repo", self.second, "--no-gh-broker"])
        self.assertEqual(rc, 0, output)
        self.assertIn(f"確保ジョブ {HOLD} に載せます", output)
        run = self.latest()
        self.assertEqual(json.loads((run / "srun-args.json").read_text())[:2], [f"--jobid={HOLD}", "--overlap"])
        self.assertIn("APPTAINERENV_AGENTRUN_SHARED_JOB=1", (run / "apptainer_exec.sh").read_text())
        self.assertIn('"${SLURM_STEP_ID:-}"', (run / "apptainer_exec.sh").read_text())
        output = self.launcher("dry-run", "assist", "--no-hold", "--repo", self.second).stdout
        self.assertIn("launch_method: srun --pty (interactive)", output)

    def test_a_hold_job_still_waiting_stops_an_interactive_launch(self):
        self.hold_job(state="PENDING")
        rc, output = self.execute(["assist", "--repo", self.second])
        self.assertEqual(rc, 2, output)
        self.assertIn("確保ジョブがまだ割り当て待ちです", output)
        self.assertFalse((self.root / ".agent-runs").exists())
        # A batch run may wait for it in its queue.
        output = self.launcher("dry-run", "assist", "--submit", "--repo", self.second, "task").stdout
        self.assertIn(f"launch_method: hold job {HOLD} (queued", output)

    def test_batch_runs_are_queued_in_the_hold_job(self):
        self.hold_job()
        result = self.launcher("assist", "--submit", "--repo", self.second, "--no-gh-broker", "task")
        pid = re.search(r"pid=(\d+)", result.stdout)
        if pid:
            self.addCleanup(lambda: os.kill(int(pid[1]), signal.SIGKILL) if Path(f"/proc/{pid[1]}").exists() else None)
        self.assertIn(f"確保ジョブ {HOLD} に投入しました", result.stdout)
        self.assertFalse(self.sbatch_log.exists())  # no job of its own
        run = self.latest()
        item = json.loads((self.folder / "queue" / f"{run.name}.json").read_text())
        self.assertEqual(item["run"], str(run))
        self.assertEqual((run / "live/hold_job.txt").read_text().strip(), HOLD)
        self.assertIn(f"hold_job: {HOLD}", (run / "capsule.yaml").read_text())
        control = next((self.root / "central-history/jobs").glob("*.json"))
        self.assertEqual((json.loads(control.read_text())["job_ref"], json.loads(control.read_text())["hold"]),
                         (HOLD, True))
        # --overlap with --submit names a hold job explicitly; any other job is refused.
        self.set_jobs({JOB: {}})
        self.assertIn("確保ジョブ（agentrun hold）だけ",
                      self.launcher("assist", "--submit", "--overlap", JOB, "task", expected=2).stderr)

    def test_cancel_takes_a_queued_run_back_or_stops_one_step(self):
        self.hold_job()
        queued = self.make_run("20261126_110000_assist_codex")
        (queued / "live/hold_job.txt").write_text(HOLD + "\n")
        (self.folder / "queue" / f"{queued.name}.json").write_text(json.dumps({"run": str(queued)}))
        self.assertIn("開始前に取り消しました", self.launcher("hold", "cancel", queued.name).stdout)
        self.assertFalse((self.folder / "queue" / f"{queued.name}.json").exists())
        self.assertTrue((queued / "live/session_finished.txt").is_file())
        self.assertEqual(json.loads((queued / "live/status.json").read_text())["status"], "cancelled")
        running = self.make_run("20261126_120000_assist_claude", "claude")
        (running / "live/slurm_job_id.txt").write_text(HOLD + "\n")
        (running / "live/slurm_step_id.txt").write_text("5\n")
        self.assertIn("確保ジョブとほかのセッションはそのまま", self.launcher("hold", "cancel", str(running)).stdout)
        self.assertEqual(self.scancel_log.read_text(), f"{HOLD}.5\n")


class HoldDispatchTests(HoldBase):
    def test_the_hold_job_starts_each_queued_run_as_a_step(self):
        steps = self.root / "steps.log"
        (self.bin / "srun").write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{steps}'\n")
        run = self.root / "run"
        (run / "live").mkdir(parents=True)
        (run / "submit.sbatch").write_text("#!/bin/sh\n")
        (self.folder / "queue/run.json").write_text(json.dumps({"run": str(run)}))
        env = dict(self.env, SLURM_CPUS_PER_TASK="8", SLURM_JOB_ID=HOLD)
        process = subprocess.Popen(["python3", str(HELPER), "dispatch", str(self.folder)], env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            deadline = time.monotonic() + 15
            while not steps.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
        finally:
            process.send_signal(signal.SIGTERM)
            output = process.communicate(timeout=10)[0]
        self.assertTrue(steps.exists(), output)
        line = steps.read_text().splitlines()[0]
        for part in ("--overlap", "--nodes=1", "--ntasks=1", "--cpus-per-task=8", f"--output={run}/live/slurm.out",
                     f"--error={run}/live/slurm.err", f"bash {run}/submit.sbatch"):
            self.assertIn(part, line)
        self.assertTrue((self.folder / "started/run.json").is_file())
        self.assertIn("開始: run", output)

    def test_history_of_a_run_in_a_hold_job_is_saved_when_its_step_ends(self):
        run = self.make_run("held-run")
        (run / "live/session_finished.txt").write_text("done\n")
        # The hold job keeps running; the run's own end marker is enough.
        with mock.patch.dict(os.environ, AGENTRUN_HISTORY_DIR=self.env["AGENTRUN_HISTORY_DIR"]), \
                mock.patch.object(history, "query_active", return_value=True), \
                mock.patch.object(history, "archive", return_value={"status": "ok"}) as archive:
            control = history.control_path(run.parent, "held-run")
            control.write_text(json.dumps({"run_id": "held-run", "job_ref": HOLD, "hold": True,
                                           "origin_host": history.socket.gethostname(), "status": "watching"}))
            history.watch(run.parent, "held-run", poll_interval=0.01)
        archive.assert_called_once()
        self.assertEqual(json.loads(control.read_text())["status"], "archived")


class HoldWizardTests(HoldBase):
    STUB = 'source "$1"; command_prepare() { printf "PREPARE_ARGS=%s\\n" "$*"; }; command_wizard'

    def wizard(self, answers):
        return self.execute([], ["1", *answers], command=["bash", "-c", self.STUB, "bash", str(LAUNCHER)])

    def test_a_hold_job_is_the_default_place(self):
        self.hold_job()
        # mode, agent, interactive, where=Enter (the hold job), repo, binds, fuse, secrets, goal, save, launch
        rc, output = self.wizard(["1", "1", "1", "", str(self.second), "n", "n", "n", "", "", "y"])
        self.assertEqual(rc, 0, output)
        self.assertIn(f"確保ジョブに載せる: job {HOLD}", output)
        line = next(l for l in output.replace("\r", "").splitlines() if l.startswith("PREPARE_ARGS="))
        self.assertIn(f"--overlap {HOLD}", line)
        self.assertNotIn("メモリ（例", output)

    def test_a_new_hold_job_is_made_at_launch(self):
        # mode, agent, interactive, where=new hold job, partition (default), time (partition limit),
        # repo, binds, fuse, secrets, goal, save, launch
        rc, output = self.wizard(["1", "1", "1", "2", "", "", str(self.second), "n", "n", "n", "", "", "y"])
        self.assertEqual(rc, 0, output)
        self.assertIn("partition gpu のノード node01 を確保します: CPU 64 / メモリ 512000MB（全部）/ GPU 4", output)
        self.assertIn("agentrun hold start --partition gpu", output)
        self.assertIn("確保ジョブ 7777 が動き始めました", output)
        line = next(l for l in output.replace("\r", "").splitlines() if l.startswith("PREPARE_ARGS="))
        self.assertIn("--overlap 7777", line)


if __name__ == "__main__":
    unittest.main()
