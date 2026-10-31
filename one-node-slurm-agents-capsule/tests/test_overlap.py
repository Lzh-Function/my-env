"""実行中ジョブへの overlap 起動を mock Slurm と PTY で検証する。"""

import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import shlex
import signal
import struct
import subprocess
import tempfile
import termios
import time
import unittest

from test_sessions import LAUNCHER, codex_history, sessions


HELPER = LAUNCHER.with_name("overlap.py")
JOB = "9001"
TRES = "cpu=8,mem=64000M,node=1,billing=8,gres/gpu=2,gres/gpu:a100=2"

MOCK_SCONTROL = r'''#!/usr/bin/env python3
import json, os, sys
jobs = json.loads(open(os.environ["TEST_SLURM_JOBS"]).read())
job = sys.argv[-1]
if job not in jobs:
    print("slurm_load_jobs error: Invalid job id specified", file=sys.stderr)
    sys.exit(1)
j = jobs[job]
print(f"JobId={job} JobName={j.get('name', 'agentrun-assist-codex')} UserId=someone({j.get('uid', os.getuid())}) "
      f"GroupId=g(1) JobState={j.get('state', 'RUNNING')} Partition=gpu NodeList=node01 NumCPUs={j.get('cpus', 8)} "
      f"TimeLimit=02:00:00 RunTime=00:10:00 ReqTRES=cpu=1 {j.get('tres', 'AllocTRES=')}")
'''

MOCK_SQUEUE = r'''#!/usr/bin/env python3
import json, os, sys
assert "--states=RUNNING" in sys.argv and f"--user" in sys.argv
for job, j in json.loads(open(os.environ["TEST_SLURM_JOBS"]).read()).items():
    if j.get("state", "RUNNING") == "RUNNING":
        print(f"{job}|gpu|node01|{j.get('cpus', 8)}|10:00|2:00:00|gres/gpu:2|{j.get('name', 'agentrun-assist-codex')}")
'''

# Records the step request; srun runs the generated script on the job's node.
MOCK_SRUN = r'''#!/usr/bin/env python3
import json, os, shlex, sys
from pathlib import Path
assert os.isatty(0)
run = Path(sys.argv[-1]).parent
(run / "srun-args.json").write_text(json.dumps(sys.argv[1:]))
job = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--jobid="))
(run / "live/slurm_job_id.txt").write_text(job + "\n")
command = shlex.split((run / "apptainer_exec.sh").read_text().splitlines()[-1])[-1]
expected = os.environ.get("TEST_EXPECT_COMMAND")
assert not expected or expected in command, command
print("MOCK_OVERLAP_READY", flush=True)
'''


class OverlapBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="overlap repo with spaces ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name, text in (("scontrol", MOCK_SCONTROL), ("squeue", MOCK_SQUEUE), ("srun", MOCK_SRUN)):
            path = self.bin / name
            path.write_text(text)
            path.chmod(0o755)
        self.jobs = self.root / "jobs.json"
        self.set_jobs({JOB: {"tres": "AllocTRES=" + TRES}})
        host_home = self.root / "host-home"
        host_home.mkdir()
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", HOME=str(host_home),
                        AGENTRUN_HISTORY_DIR=str(self.root / "central-history"), TEST_SLURM_JOBS=str(self.jobs),
                        WIZARD_UI="plain", TERM="dumb", INPUTRC="/dev/null")
        self.second = self.root / "second repo"
        self.second.mkdir()

    def set_jobs(self, jobs):
        self.jobs.write_text(json.dumps(jobs))

    def helper(self, *args, expected=0, env=None):
        result = subprocess.run(["python3", str(HELPER), *map(str, args)], capture_output=True, text=True,
                                env=env or self.env, cwd=self.root, timeout=20)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def launcher(self, *args, expected=0):
        result = subprocess.run([str(LAUNCHER), *map(str, args)], capture_output=True, text=True,
                                env=self.env, cwd=self.root, timeout=30)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def execute(self, args, answers=(), command=None, env=None):
        """Drive the launcher on a PTY, answering each prompt in order."""
        master, slave = pty.openpty()
        proc = None
        try:
            def controlling_terminal():
                os.setsid()
                fcntl.ioctl(0, termios.TIOCSCTTY, 0)

            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 200, 0, 0))
            proc = subprocess.Popen(command or [str(LAUNCHER), *map(str, args)], cwd=self.root, env=env or self.env,
                                    stdin=slave, stdout=slave, stderr=slave, preexec_fn=controlling_terminal)
            prompts = re.compile(
                rb'\x1b\[1;36m[^\r\n]*:cancel=[^\r\n]*\x1b\[0m\r?\n'
                rb'|#\? \(Enter=1, :back, :cancel\) |\(:back, :cancel\): '
            )
            output = bytearray()
            sent = 0
            deadline = time.monotonic() + 20
            while proc.poll() is None:
                if time.monotonic() > deadline:
                    self.fail(f"Sent {sent}/{len(answers)} replies: {output!r}")
                if select.select([master], [], [], 0.05)[0]:
                    output.extend(os.read(master, 65536))
                if sent < len(answers) and sent < len(prompts.findall(output)):
                    if termios.tcgetattr(slave)[3] & termios.ICANON:
                        continue
                    reply = answers[sent].encode()
                    os.write(master, (b"\x15" + reply if reply else b"") + b"\n")
                    sent += 1
            while select.select([master], [], [], 0)[0]:
                output.extend(os.read(master, 65536))
            self.assertEqual(sent, len(answers), output.decode(errors="replace"))
            return proc.returncode, output.decode(errors="replace")
        finally:
            if proc is not None and proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
            os.close(master)
            os.close(slave)

    def latest(self):
        return (self.root / ".agent-runs/latest").resolve()


class OverlapHelperTests(OverlapBase):
    def test_info_reports_job_resources_and_gpu_forms(self):
        lines = self.helper("info", JOB).stdout.splitlines()
        self.assertEqual(lines, [JOB, "8", "2", "gpu", "node01", "02:00:00", "00:10:00", "agentrun-assist-codex"])
        for tres, gpus in (("AllocTRES=cpu=4,mem=1G,node=1", "0"),
                           ("AllocTRES=cpu=4,gres/gpu:a100=1,gres/gpu:v100=2", "3"),
                           ("TRES=cpu=4,mem=1G,gres/gpu=1", "1"),
                           ("TresPerNode=gres:gpu:4", "4")):
            with self.subTest(tres=tres):
                self.set_jobs({JOB: {"tres": tres, "name": "job with spaces"}})
                lines = self.helper("info", JOB).stdout.splitlines()
                self.assertEqual(lines[2], gpus)
                self.assertEqual(lines[7], "job with spaces")

    def test_info_rejects_jobs_that_cannot_be_joined(self):
        cases = (({"state": "PENDING"}, "実行中ではありません"),
                 ({"uid": os.getuid() + 1}, "自分のジョブではありません"))
        for job, message in cases:
            with self.subTest(job=job):
                self.set_jobs({JOB: job})
                self.assertIn(message, self.helper("info", JOB, expected=2).stderr)
        self.assertIn("見つかりません", self.helper("info", "123", expected=2).stderr)
        self.assertIn("数字", self.helper("info", "12;rm", expected=2).stderr)

    def test_jobs_list_running_jobs_and_matching_agentrun_runs(self):
        self.set_jobs({JOB: {}, "9002": {"state": "PENDING"}, "9003": {"name": "a|b c"}})
        for name in ("20261031_100000_assist_codex", "20261031_110000_assist_claude"):
            (self.root / ".agent-runs" / name / "live").mkdir(parents=True)
            (self.root / ".agent-runs" / name / "live/slurm_job_id.txt").write_text(JOB + "\n")
        lines = self.helper("jobs", self.root / ".agent-runs").stdout.splitlines()
        self.assertEqual([line.split()[0] for line in lines], [JOB, "9003"])
        self.assertIn("CPU=8", lines[0])
        self.assertIn("agentrun=20261031_100000_assist_codex ほか1件", lines[0])
        self.assertIn("a|b c", lines[1])

    def test_jobs_without_slurm_or_with_query_failure_offer_nothing(self):
        (self.bin / "squeue").unlink()
        self.assertEqual(self.helper("jobs", self.root).stdout, "")
        (self.bin / "squeue").write_text("#!/bin/sh\necho down >&2\nexit 1\n")
        (self.bin / "squeue").chmod(0o755)
        result = self.helper("jobs", self.root)
        self.assertEqual(result.stdout, "")
        self.assertIn("確認できません", result.stderr)


class OverlapLaunchTests(OverlapBase):
    def test_assist_overlap_starts_separate_capsule_inside_running_job(self):
        extra = self.root / "overlap data"
        extra.mkdir()
        rc, output = self.execute(["assist", "--agent", "claude", "--overlap", JOB, "--repo", self.second,
                                   "--bind", f"{extra}:/overlap-data:ro", "--no-gh-broker"])
        self.assertEqual(rc, 0, output)
        self.assertIn("MOCK_OVERLAP_READY", output)
        run = self.latest()
        self.assertEqual(json.loads((run / "srun-args.json").read_text())[:6],
                         [f"--jobid={JOB}", "--overlap", "--nodes=1", "--ntasks=1", "--cpus-per-task=8", "--pty"])
        srun = " ".join(json.loads((run / "srun-args.json").read_text()))
        for option in ("--time", "--mem", "--partition", "--gres"):
            self.assertNotIn(option, srun)
        command = shlex.split((run / "apptainer_exec.sh").read_text().splitlines()[-1])
        self.assertIn("--nv", command)
        self.assertIn(f"{self.second}:/workspace:rw", command)
        self.assertIn(f"{extra}:/overlap-data:ro", command)
        self.assertIn(f"overlap_job: {JOB}", (run / "capsule.yaml").read_text())
        self.assertIn(f"shared with Slurm job {JOB}", (run / "prompt.txt").read_text())
        saved = json.loads((run / "launch.json").read_text())
        self.assertEqual(saved["overlap_job"], JOB)
        self.assertEqual((saved["options"]["cpus"], saved["options"]["gpus"], saved["options"]["partition"]),
                         ("8", "2", "gpu"))
        replay = subprocess.run(["python3", str(LAUNCHER.with_name("run_settings.py")), "args", run],
                                capture_output=True, timeout=10).stdout.split(b"\0")
        self.assertNotIn(b"--overlap", replay)
        self.assertFalse((run / "home").exists())
        self.assertEqual((run / "live/slurm_job_id.txt").read_text().strip(), JOB)

    def test_overlap_is_only_for_interactive_launches(self):
        for args in (["assist", "--submit", "--overlap", JOB, "task"], ["experiment", "--overlap", JOB, "task"],
                     ["dry-run", "review", "--overlap", JOB, "task"]):
            with self.subTest(args=args):
                self.assertIn("対話式の assist と resume だけ", self.launcher(*args, expected=2).stderr)
        self.assertIn("numeric", self.launcher("assist", "--overlap", "abc", expected=2).stderr)
        self.assertFalse((self.root / ".agent-runs").exists())

    def test_locked_repo_or_ended_job_stops_before_creating_a_run(self):
        with (self.second / ".agentrun.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            rc, output = self.execute(["assist", "--overlap", JOB, "--repo", self.second])
        self.assertEqual(rc, 1, output)
        self.assertIn("git worktree", output)
        self.set_jobs({JOB: {"state": "COMPLETED"}})
        rc, output = self.execute(["assist", "--overlap", JOB, "--repo", self.second])
        self.assertEqual(rc, 2, output)
        self.assertIn("実行中ではありません", output)
        self.assertFalse((self.root / ".agent-runs").exists())

    def test_dry_run_shows_step_command_without_creating_a_run(self):
        output = self.launcher("dry-run", "assist", "--overlap", JOB, "--repo", self.second).stdout
        self.assertIn(f"slurm_command: srun --jobid={JOB} --overlap --nodes=1 --ntasks=1 --cpus-per-task=8 --pty",
                      output)
        self.assertIn(f"overlap_job: {JOB}\n", output)
        self.assertIn(f"Resources: shared with Slurm job {JOB}", output)
        self.assertIn(" --nv ", output)
        self.assertFalse((self.root / ".agent-runs").exists())


class OverlapResumeTests(OverlapBase):
    def setUp(self):
        super().setUp()
        parent = self.root / ".agent-runs"
        parent.mkdir()
        self.original = parent / "overlap-source"
        self.original.mkdir()
        sessions.init(self.original, "codex", str(self.second), "assist")
        codex_history(sessions.state_dir(self.original, sessions.manifest(self.original)))
        self.env["TEST_EXPECT_COMMAND"] = "codex resume 12345678-1234-1234-1234-123456789abc"

    def test_resume_can_join_running_job(self):
        rc, output = self.execute(["resume", self.original.name, "--overlap", JOB], ["y"])
        self.assertEqual(rc, 0, output)
        self.assertIn(f"Slurm job {JOB} に overlap して対話再開", output)
        run = self.latest()
        self.assertNotEqual(run, self.original)
        self.assertEqual(json.loads((run / "srun-args.json").read_text())[:2], [f"--jobid={JOB}", "--overlap"])

    def test_wizard_resume_offers_running_job(self):
        # mode=resume, run=1, preview=no, overlap=job, binds=no, launch=yes
        rc, output = self.execute(["wizard"], ["6", "1", "n", "2", "n", "y"])
        self.assertEqual(rc, 0, output)
        self.assertIn("このジョブに overlap して", output)
        self.assertIn(f"--overlap {JOB}", output)
        self.assertNotIn("Memory (e.g.", output)
        self.assertEqual(json.loads((self.latest() / "srun-args.json").read_text())[0], f"--jobid={JOB}")


class OverlapWizardTests(OverlapBase):
    STUB = 'source "$1"; command_prepare() { printf "PREPARE_ARGS=%s\\n" "$*"; }; command_wizard'

    def wizard(self, answers):
        return self.execute([], answers, command=["bash", "-c", self.STUB, "bash", str(LAUNCHER)])

    def test_assist_asks_to_overlap_and_skips_resource_questions(self):
        # mode, agent, interactive, overlap=job, repo, binds, fuse, secrets, goal, launch
        rc, output = self.wizard(["1", "1", "1", "2", str(self.second), "n", "n", "n", "", "y"])
        self.assertEqual(rc, 0, output)
        self.assertIn("このジョブに overlap して、同じ割り当て内でエージェントコンテナをもう一つ起動しますか？", output)
        self.assertIn(f"overlap: job {JOB} (agentrun-assist-codex) / node: node01", output)
        line = next(l for l in output.replace("\r", "").splitlines() if l.startswith("PREPARE_ARGS="))
        self.assertIn(f"--overlap {JOB}", line)
        self.assertNotIn("--mem", line)
        self.assertNotIn("Memory (e.g.", output)

    def test_declining_overlap_keeps_normal_resource_flow(self):
        rc, output = self.wizard(["1", "1", "1", "1", "", "", "", "", "", "", "n", "n", "n", "", "y"])
        self.assertEqual(rc, 0, output)
        line = next(l for l in output.replace("\r", "").splitlines() if l.startswith("PREPARE_ARGS="))
        self.assertNotIn("--overlap", line)
        self.assertIn("--mem", line)

    def test_batch_and_jobless_launches_do_not_ask(self):
        rc, output = self.wizard(["1", "1", "2", "", "", "", "", "", "", "n", "n", "n", "", "task", "y"])
        self.assertEqual(rc, 0, output)
        self.assertNotIn("overlap して", output)
        self.set_jobs({})
        (Path(self.env["HOME"]) / ".agentrun/wizard-last").unlink()
        rc, output = self.wizard(["1", "1", "1", "", "", "", "", "", "", "n", "n", "n", "", "y"])
        self.assertEqual(rc, 0, output)
        self.assertNotIn("overlap して", output)

    def test_overlap_repo_in_use_is_rejected_in_wizard(self):
        with (self.second / ".agentrun.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            rc, output = self.wizard(["1", "1", "1", "2", str(self.second), str(self.root), "n", "n", "n", "", "y"])
        self.assertEqual(rc, 0, output)
        self.assertIn("choose another repository or a git worktree", output)
        line = next(l for l in output.replace("\r", "").splitlines() if l.startswith("PREPARE_ARGS="))
        self.assertIn(f"--repo {self.root}", line)


if __name__ == "__main__":
    unittest.main()
