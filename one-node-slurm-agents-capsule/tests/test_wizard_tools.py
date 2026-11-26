"""wizard の入口メニューと「その他の機能」を、PTY と mock Slurm で操作して確かめる。"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_wizard
from test_sessions import codex_history, sessions

MOCK_SQUEUE = r'''#!/usr/bin/env python3
import sys
assert "--states=RUNNING" in sys.argv
'''


class WizardToolTests(unittest.TestCase):
    execute = test_wizard.WizardTests.execute

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="wizard tools ")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "squeue").write_text(MOCK_SQUEUE)
        (self.bin / "squeue").chmod(0o755)
        home = self.root / "host-home"
        home.mkdir()
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", HOME=str(home),
                        AGENTRUN_HISTORY_DIR=str(self.root / "central-history"),
                        WIZARD_UI="plain", TERM="dumb", INPUTRC="/dev/null")

    def wizard(self, answers, expected=0):
        rc, output = self.execute(["wizard"], "".join(f"{answer}\n" for answer in answers))
        self.assertEqual(rc, expected, output)
        return output

    def make_run(self):
        run = self.root / ".agent-runs/20261117_090000_assist_codex"
        run.mkdir(parents=True)
        sessions.init(run, "codex", str(self.root), "assist")
        (run / "live").mkdir(exist_ok=True)
        (run / "live/slurm.out").write_text("line one\nTRAINING LOSS 0.25\n")
        (run / "live/status.json").write_text(json.dumps({"status": "success"}))
        (run / "artifacts").mkdir(exist_ok=True)
        (run / "artifacts/run_title.txt").write_text("trained baseline model\n")
        return run

    def test_back_from_the_first_menu_ends_and_other_features_list_running_sessions(self):
        output = self.wizard(["2", "1", "", ":back", ":back"])
        self.assertIn("agentrun wizard — 何をしますか？", output)
        self.assertIn("その他の機能 — どれを使いますか？", output)
        self.assertIn("実行中の agentrun はありません。", output)
        self.assertIn("完了しました。", output)
        self.assertIn("wizard を終了しました", output)
        self.assertFalse((self.root / ".agent-runs").exists())

    def test_pick_a_run_and_read_its_log(self):
        run = self.make_run()
        # tools → runs → the run → logs → slurm.out → last 200 lines → Enter → cancel.
        output = self.wizard(["2", "2", "1", "1", "1", "1", "", ":cancel"], expected=130)
        self.assertIn("20261117_090000_assist_codex  codex assist  [終了: success]  trained baseline model", output)
        self.assertIn("作業リポジトリ: " + str(self.root), output)
        self.assertIn("slurm.out（", output)
        self.assertIn("TRAINING LOSS 0.25", output)
        self.assertTrue((run / "live/slurm.out").exists())

    def test_a_finished_conversation_can_be_resumed_from_the_run_menu(self):
        run = self.make_run()
        codex_history(sessions.state_dir(run, sessions.manifest(run)), text="前回の最後の発言")
        (run / "live/session_finished.txt").write_text("done\n")  # the session has ended
        # tools → runs → the run → resume → decline at the CLI's own confirmation → Enter → cancel.
        output = self.wizard(["2", "2", "1", "1", "n", "", ":cancel"], expected=130)
        self.assertIn("この run の会話を再開する", output)
        self.assertIn("この設定を引き継いで再開しますか？", output)
        self.assertIn("再開を中止しました。新しい実行は作成していません。", output)
        self.assertEqual(sorted(p.name for p in run.parent.iterdir() if not p.name.startswith(".")), [run.name])

    def test_run_status_and_verify_are_reachable(self):
        self.make_run()
        output = self.wizard(["2", "2", "1", "2", "", "3", "", ":cancel"], expected=130)
        self.assertIn('"status": "success"', output)
        self.assertIn("[OK] run directory", output)

    def test_batch_collection_is_offered_only_for_a_pending_batch_run(self):
        import subprocess
        import sys
        run = self.make_run()
        # Interactive runs have these too, so they must not count as a batch run.
        (run / "submit.sbatch").write_text("#!/bin/bash\n")
        (run / "live/slurm_job_id.txt").write_text("4242\n")

        def offered():
            menu = Path(__file__).resolve().parents[1] / "runtime/agentrun/run_menu.py"
            return subprocess.run([sys.executable, str(menu), "batch", str(run)], env=self.env,
                                  capture_output=True, check=False).returncode == 0

        self.assertFalse(offered())
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime/agentrun"))
        from history_export import archive_key
        jobs = self.root / "central-history/jobs"
        jobs.mkdir(parents=True)
        control = jobs / (archive_key(run.parent, sessions.manifest(run)["run_id"]) + ".json")
        control.write_text(json.dumps({"status": "watching", "job_ref": "4242"}))
        self.assertTrue(offered())
        control.write_text(json.dumps({"status": "archived", "job_ref": "4242"}))
        self.assertFalse(offered())

    def test_history_menu_reports_an_empty_archive(self):
        output = self.wizard(["2", "3", "1", "", "", ":cancel"], expected=130)
        self.assertIn("保存された会話はまだありません", output)

    def test_goal_file_is_created_after_confirmation(self):
        output = self.wizard(["2", "8", "2", "y", "", ":cancel"], expected=130)
        self.assertTrue((self.root / "goal.yaml").is_file())
        self.assertIn("goal.yaml を作りました", output)

    def test_auth_status_and_agent_check_run_their_commands(self):
        output = self.wizard(["2", "5", "1", "", ":back", "7", "2", "", ":cancel"], expected=130)
        self.assertIn("認証の状態", output)
        self.assertIn("使えるエージェント:", output)

    def test_failing_command_keeps_the_wizard_running(self):
        # skill-install with a missing source exits with an error inside its subshell.
        output = self.wizard(["2", "8", "1", str(self.root / "missing"), "", "n", "", ":cancel"], expected=130)
        self.assertIn("終了コード", output)
        self.assertIn("スキルの追加と目標ファイル", output.split("終了コード", 1)[1])

    def test_every_other_menu_reaches_its_command(self):
        export = self.root / "vault/agent history"
        answers = [
            "2",
            "3", "2", "loss", "",                    # history → search
            "3",                                     # history → rename (nothing archived yet)
            "4", str(export), "y", "y", "", ":back",  # history → export, saving running sessions first
            "4", "3", ":back",                        # templates → show (none yet) → back
            "5", "3", "1", "", ":back",               # auth → import → claude
            "7", "1", "1", "",                        # checks → doctor → claude
            "4", "1", "n", "",                        # checks → smoke-test → claude → prepare only
            "3", "", ":cancel",                       # checks → validate
        ]
        output = self.wizard(answers, expected=130)
        self.assertIn("会話履歴の検索: loss", output)
        self.assertIn("保存された会話はまだありません", output)
        self.assertIn("会話履歴の書き出し", output)
        self.assertIn("実行中のセッションはありません", output)
        self.assertIn("テンプレートはまだありません", output)
        self.assertIn("== 認証の取り込み ==", output)
        self.assertIn("ホストにありません", output)
        self.assertIn("[OK] command:python3", output)
        self.assertIn("smoke-test の準備をしました", output)
        self.assertIn("== validate ==", output)
        self.assertTrue(any((self.root / ".agent-runs").glob("*smoke-test*")))

    def test_hold_menu_shows_the_hold_job_state(self):
        # A queue with no hold jobs; tools → hold job → status → back to the menu → cancel
        (self.root / "bin/squeue").write_text("#!/bin/sh\nexit 0\n")
        output = self.wizard(["2", "9", "1", "", ":cancel"], expected=130)
        self.assertIn("確保ジョブ — どうしますか？", output)
        self.assertIn("== 確保ジョブの状態 ==", output)
        self.assertIn("確保ジョブはありません", output)

    def test_rename_a_conversation_from_the_history_menu(self):
        import history
        run = self.make_run()
        codex_history(sessions.state_dir(run, sessions.manifest(run)))
        with patch.dict(os.environ, AGENTRUN_HISTORY_DIR=self.env["AGENTRUN_HISTORY_DIR"]):
            history.archive(run)
        # tools → history → rename → the only conversation → replace the prefilled name → Enter → cancel.
        output = self.wizard(["2", "3", "3", "1", "\x15発表の図の修正", "", ":cancel"], expected=130)
        self.assertIn("名前を変える会話を選んでください", output)
        self.assertIn("trained baseline model", output)
        self.assertIn("名前を変えました: trained baseline model → 発表の図の修正", output)
        titles = json.loads((self.root / "central-history/titles.json").read_text())
        self.assertEqual([entry["title"] for entry in titles.values()], ["発表の図の修正"])

    def test_daily_export_is_set_and_removed_from_the_history_menu(self):
        table = self.root / "crontab.txt"
        (self.bin / "crontab").write_text(
            '#!/bin/sh\nif [ "$1" = -l ]; then [ -f "$TABLE" ] || { echo "no crontab for tester" >&2; exit 1; }; '
            'cat "$TABLE"; else cat > "$TABLE"; fi\n')
        (self.bin / "crontab").chmod(0o755)
        self.env.update(TABLE=str(table), TZ="Asia/Tokyo")
        self.env.pop("AGENTRUN_TIMEZONE", None)
        vault = self.root / "vault"
        # tools → history → schedule → add → folder → time → back; then schedule → remove → cancel.
        output = self.wizard(["2", "3", "5", "1", str(vault), "", "", "5", "2", "", ":cancel"], expected=130)
        self.assertIn("自動書き出しは登録されていません", output)
        self.assertIn(f"毎日 04:00（Asia/Tokyo）に、{vault} へ会話履歴を書き出すように登録しました。", output)
        self.assertIn(f"毎日 04:00（Asia/Tokyo）に {vault} へ書き出します。", output)
        self.assertIn("毎日の自動書き出しを解除しました。", output)
        self.assertEqual(table.read_text(), "")

    def test_dry_run_previews_without_creating_a_run(self):
        # tools → dry-run → assist / claude / interactive → where: a job of its own → repo and resources
        # as is → no binds, no FUSE, no goal → no template → run the dry-run → stop.
        answers = ["2", "6", "1", "1", "1", "", "", "", "", "", "", "", "n", "n", "n", "", "", "y", "", "3"]
        output = self.wizard(answers)
        self.assertIn("実行モードを選んでください（dry-run：起動せずに確認します）", output)
        self.assertNotIn("resume（保存した会話を再開する）", output)
        self.assertIn("host_run_directory:", output)
        self.assertIn("dry-run だけで終了しました。起動はしていません。", output)
        runs = self.root / ".agent-runs"
        self.assertFalse(runs.exists() and any(runs.iterdir()))


if __name__ == "__main__":
    unittest.main()
