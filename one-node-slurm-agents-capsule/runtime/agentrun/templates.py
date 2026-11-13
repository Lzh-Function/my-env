#!/usr/bin/env python3
"""起動設定のテンプレート（名前付き）を保存・読み出し・削除する。シェルコードとして評価しない。

テンプレートは agentrun の起動オプション列そのもの（--repo, --bind, --mem ...）と
mode・agent・起動方法・レビュー用の環境変数を持つ。Slurm の job ID と prompt は
起動ごとに変わるので持たない。
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import run_settings
import sessions

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
MODES = ("assist", "experiment", "campaign", "review", "multi-review")
# テンプレートに入れてよい起動オプション。値を取るものと取らないもの。
VALUE_OPTIONS = {"--repo", "--goal", "--gpus", "--mem", "--cpus", "--time", "--partition", "--bind",
                 "--secrets-file", "--reviewers", "--target-diff", "--target-report", "--agents"}
FLAG_OPTIONS = {"--allow-fuse", "--no-allow-fuse", "--no-secrets", "--gh-broker", "--no-gh-broker"}


def store():
    return Path(os.environ.get("AGENTRUN_TEMPLATE_DIR") or Path.home() / ".agentrun/templates")


def path_of(name):
    if not NAME.fullmatch(name):
        raise ValueError("テンプレート名には英数字と . _ - だけを使えます（先頭は英数字、64文字まで）: " + name)
    return store() / (name + ".json")


def check_args(args):
    index = 0
    while index < len(args):
        option = args[index]
        if option in VALUE_OPTIONS and index + 1 < len(args):
            index += 2
        elif option in FLAG_OPTIONS:
            index += 1
        else:
            raise ValueError("テンプレートに入れられないオプションです: " + option)
    if any("\0" in value for value in args):
        raise ValueError("設定に NUL 文字は使えません")


def load(name):
    path = path_of(name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError("テンプレートがありません: " + name) from None
    if (not isinstance(data, dict) or data.get("version") != 1 or data.get("mode") not in MODES
            or data.get("agent") not in sessions.MOUNTS or data.get("submit") not in (0, 1)
            or not isinstance(data.get("args"), list) or not all(isinstance(v, str) for v in data["args"])
            or not isinstance(data.get("env"), dict)
            or any(k not in run_settings.REVIEW_ENV or not isinstance(v, str) for k, v in data["env"].items())):
        raise ValueError("テンプレートの形式が不正です: " + str(path))
    check_args(data["args"])
    return data


def save(name, data, force):
    path = path_of(name)
    check_args(data["args"])
    if path.exists() and not force:
        raise FileExistsError("同じ名前のテンプレートがあります: " + name)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = {"version": 1, "name": name, "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"), **data}
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        tmp.chmod(0o600)
        stream.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def from_run(run):
    """実行中・終了済みの run が保存した起動設定をテンプレートにする。"""
    manifest = sessions.manifest(run)
    if manifest["mode"] not in MODES:
        raise ValueError("この run の mode はテンプレートにできません: " + manifest["mode"])
    env = run_settings.load(run)["review_env"]
    return {"mode": manifest["mode"], "agent": manifest["agent"], "submit": 0,
            "args": run_settings.args(run), "env": env, "source": "run " + manifest["run_id"]}


def names(mode=None):
    result = []
    for path in sorted(store().glob("*.json")) if store().is_dir() else []:
        try:
            data = load(path.stem)
        except (ValueError, OSError, UnicodeError):
            continue
        if mode is None or data["mode"] == mode:
            result.append((path.stem, data))
    return result


def option(args, key):
    values = [args[i + 1] for i in range(len(args) - 1) if args[i] == key]
    return values[-1] if values else ""


def summary(name, data):
    args = data["args"]
    binds = [args[i + 1] for i in range(len(args) - 1) if args[i] == "--bind"]
    parts = [name, data["mode"], data["agent"], "repo=" + (option(args, "--repo") or "-")]
    parts.append(f"bind={len(binds)}件")
    return "  ".join(sessions.safe_text(part) for part in parts)


def describe(name, data):
    args = data["args"]
    lines = [f"テンプレート: {name}（保存 {data.get('saved_at', '?')}、元: {data.get('source', '?')}）",
             f"  mode / agent / 起動: {data['mode']} / {data['agent']} / {'sbatch' if data['submit'] else '対話または準備のみ'}"]
    i = 0
    while i < len(args):
        if args[i] in VALUE_OPTIONS:
            lines.append(f"  {args[i]} {args[i + 1]}")
            i += 2
        else:
            lines.append(f"  {args[i]}")
            i += 1
    lines.extend(f"  {key}={value}" for key, value in data["env"].items())
    return "\n".join(sessions.safe_text(line) for line in lines)


def running_jobs():
    import overlap
    try:
        output = overlap.query(["squeue", "--noheader", "--user", str(os.getuid()), "--states=RUNNING", "--format=%A"])
    except RuntimeError:
        return set()
    return {line.strip() for line in output.splitlines() if line.strip()}


def registered_runs():
    """起動時に登録簿（~/.agentrun/active-runs）へ記録された run。起動したディレクトリを問わない。"""
    import auth_sync
    directory = auth_sync.registry(Path.home() / ".agentrun/auth")
    found = []
    for link in sorted(directory.iterdir()) if directory.is_dir() else []:
        run = Path(os.path.realpath(link))
        if link.is_symlink() and run.is_dir():
            found.append(run)
    return found


def all_runs(parent):
    """今いるディレクトリの run と登録簿の run（重複は除く）。"""
    unique = {}
    for run in [*sessions.runs(parent), *registered_runs()]:
        unique.setdefault(run.resolve(), None)
    return list(unique)


def resolve_run(parent, target):
    """run ID か run ディレクトリ。今いるディレクトリになければ登録簿から探す。"""
    try:
        return sessions.resolve(parent, target)
    except ValueError:
        pass
    matches = []
    for run in registered_runs():
        data = sessions.read_json(run / "session.json")
        if run.name == target or (isinstance(data, dict) and data.get("run_id") == target):
            matches.append(run)
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise ValueError("同じ run ID が複数あります。run ディレクトリで指定してください: "
                         + ", ".join(str(run) for run in matches))
    raise ValueError("run ID が見つかりません（このディレクトリの .agent-runs と起動中 run の登録簿を探しました）: " + target)


def candidate_runs(parent):
    """テンプレートにできる run。実行中のものを先に並べる。"""
    running = running_jobs()
    rows = []
    for run in all_runs(parent):
        try:
            manifest = sessions.manifest(run)
            if manifest["mode"] not in MODES:
                continue
            run_settings.load(run)
        except (ValueError, OSError, UnicodeError):
            continue
        try:
            job = (run / "live/slurm_job_id.txt").read_text().strip()
        except OSError:
            job = ""
        active = job in running
        label = "  ".join(sessions.safe_text(part) for part in (
            run.name, manifest["agent"], "repo=" + manifest["repo"], f"[実行中 job {job}]" if active else "[終了]"))
        rows.append((not active, label))
    return [label for _, label in sorted(rows, key=lambda row: row[0])]


def nul(values):
    for value in values:
        if "\0" in value:
            raise ValueError("設定に NUL 文字は使えません")
        sys.stdout.buffer.write(value.encode() + b"\0")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("list", "show", "load", "save", "from-run", "delete", "runs", "exists"))
    parser.add_argument("target", nargs="?")
    parser.add_argument("--mode", choices=MODES)
    parser.add_argument("--agent", choices=tuple(sessions.MOUNTS))
    parser.add_argument("--submit", type=int, choices=(0, 1), default=0)
    parser.add_argument("--source", default="")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--run", type=Path)
    # 起動オプションは "--" の後ろに置き、ここでは解釈しない。
    argv = sys.argv[1:]
    rest = argv[argv.index("--") + 1:] if "--" in argv else []
    options = parser.parse_args(argv[:argv.index("--")] if "--" in argv else argv)
    try:
        if options.action == "list":
            for name, data in names(options.mode):
                print(summary(name, data))
        elif options.action == "show":
            print(describe(options.target, load(options.target)))
        elif options.action == "exists":
            return 0 if path_of(options.target).is_file() else 1
        elif options.action == "load":
            data = load(options.target)
            nul([data["mode"], data["agent"], str(data["submit"]), str(len(data["args"])), *data["args"],
                 *[part for pair in data["env"].items() for part in pair]])
        elif options.action == "save":
            env = {key: os.environ[key] for key in run_settings.REVIEW_ENV if os.environ.get(key)}
            save(options.target, {"mode": options.mode, "agent": options.agent, "submit": options.submit,
                                  "args": rest, "env": env, "source": options.source or "agentrun"}, options.force)
            print("テンプレートを保存しました: " + options.target)
        elif options.action == "from-run":
            if len(rest) != 1:
                raise ValueError("run ID か run ディレクトリを1つ指定してください")
            run = resolve_run(Path(options.run or "."), rest[0])
            save(options.target, from_run(run), options.force)
            print(f"テンプレートを保存しました: {options.target}（{run.name} から）")
        elif options.action == "delete":
            path = path_of(options.target)
            if not path.is_file():
                raise ValueError("テンプレートがありません: " + options.target)
            path.unlink()
            print("テンプレートを削除しました: " + options.target)
        elif options.action == "runs":
            for label in candidate_runs(Path(options.target)):
                print(label)
    except FileExistsError as error:
        print("agentrun template: " + str(error), file=sys.stderr)
        return 3
    except (ValueError, OSError, UnicodeError) as error:
        print("agentrun template: " + str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
