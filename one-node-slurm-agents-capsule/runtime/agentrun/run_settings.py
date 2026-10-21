#!/usr/bin/env python3
"""Persist launch options and CLI config files; omit authentication files."""

import argparse
import json
import os
import re
import secrets
import shlex
import stat
import sys
from pathlib import Path

REVIEW_ENV = (
    "AGENT_REVIEW_CODEX_MODEL",
    "AGENT_REVIEW_CODEX_EFFORT",
    "AGENT_REVIEW_CLAUDE_MODEL",
    "AGENT_REVIEW_CLAUDE_EFFORT",
    "AGENT_REVIEW_MAX_EXCHANGES",
    "AGENT_REVIEW_ACTIVE_TIMEOUT",
    "AGENT_REVIEW_REPLY_TIMEOUT",
    "AGENT_REVIEW_THREAD_TIMEOUT",
)
CONFIG = {"claude": ".claude/settings.json", "codex": ".codex/config.toml"}
VALUE_OPTIONS = (
    "repo",
    "mem",
    "cpus",
    "time",
    "partition",
    "gpus",
    "goal",
    "reviewers",
    "target-diff",
    "target-report",
    "agents",
)
MAX_SIZE = 2 * 1024 * 1024


def directory(root, parts, create=False):
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts:
            if part in (".", ".."):
                raise ValueError("設定の保存先が不正です")
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def read(path, root=None):
    parent = directory(root, path.relative_to(root).parts[:-1]) if root else None
    try:
        descriptor = os.open(
            path.name if root else path,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=parent,
        )
    finally:
        if parent is not None:
            os.close(parent)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError(f"通常の設定ファイルではありません: {path}")
        data = stream.read(MAX_SIZE + 1)
    if len(data) > MAX_SIZE:
        raise ValueError(f"設定ファイルが大きすぎます: {path}")
    return data


def atomic(path, data, root):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent = directory(root, path.relative_to(root).parts[:-1], create=True)
    temporary = ".settings-" + secrets.token_hex(12)
    try:
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
    finally:
        try:
            os.unlink(temporary, dir_fd=parent)
        except FileNotFoundError:
            pass
        os.close(parent)


def manifest(run):
    data = json.loads(read(run / "session.json"))
    if not isinstance(data, dict) or data.get("agent") not in CONFIG:
        raise ValueError("セッション情報が不正です")
    return data


def absolute(path, cwd):
    value = Path(path).expanduser()
    return str((value if value.is_absolute() else cwd / value).resolve())


def bind(spec, cwd):
    parts = spec.split(":")
    if not parts[0] or len(parts) > 3:
        raise ValueError(f"bind の形式が不正です: {spec}")
    parts[0] = absolute(parts[0], cwd)
    if len(parts) == 1:
        parts.append(parts[0])
    if not parts[1].startswith("/") or (
        len(parts) == 3 and parts[2] not in ("ro", "rw")
    ):
        raise ValueError(f"bind の形式が不正です: {spec}")
    return ":".join(parts)


def legacy(run):
    """Read old generated shell scripts as data; never execute or source them."""
    data = manifest(run)
    cwd = Path(data.get("launcher_cwd") or run.parent.parent)
    options = {"repo": data["repo"], "gpus": "0", "partition": ""}
    result = {
        "version": 1,
        "legacy": True,
        "options": options,
        "binds": [],
        "allow_fuse": False,
        "secrets_file": "",
        "gh_env_file": "",
        "review_env": {},
    }
    script = run / "submit.sbatch"
    if script.is_file():
        names = {
            "mem": "mem",
            "cpus-per-task": "cpus",
            "time": "time",
            "partition": "partition",
        }
        for line in read(script).decode().splitlines():
            if not line.startswith("#SBATCH "):
                continue
            for word in shlex.split(line[len("#SBATCH ") :]):
                key, _, value = (word.removeprefix("--")).partition("=")
                if key in names:
                    options[names[key]] = value
                elif key == "gres" and re.fullmatch(r"gpu:\d+", value):
                    options["gpus"] = value.split(":")[-1]
    script = run / "apptainer_exec.sh"
    if not script.is_file():
        return result
    lines = read(script).decode().splitlines()
    command = next(
        (line for line in reversed(lines) if line.startswith("apptainer exec")), ""
    )
    words = shlex.split(command)
    session_destinations = (
        "/home/sandbox/.codex/sessions",
        "/home/sandbox/.codex/archived_sessions",
        "/home/sandbox/.codex/sqlite",
        "/home/sandbox/.claude/projects",
        "/home/sandbox/.claude/file-history",
        "/home/sandbox/.claude/todos",
        "/home/sandbox/.claude/tasks",
        "/home/sandbox/.claude/plans",
        "/reviewer-sessions",
    )
    # Extra mounts occur after the last persistent-session mount in generated commands.
    last_session = -1
    for index, word in enumerate(words[:-1]):
        if word == "--bind" and words[index + 1].split(":")[1:2] in [
            [p] for p in session_destinations
        ]:
            last_session = index
    for index, word in enumerate(words[:-1]):
        value = words[index + 1]
        if word == "--bind" and index > last_session >= 0:
            if value.split(":")[0] == "/dev/fuse":
                result["allow_fuse"] = True
            else:
                result["binds"].append(bind(value, cwd))
        elif word == "--env-file":
            # Apptainer's env-file option is CSV-encoded as well as shell-quoted.
            import csv

            result["secrets_file"] = absolute(next(csv.reader([value]))[0], cwd)
        elif word == "--env" and "=" in value:
            key, content = value.split("=", 1)
            if key in REVIEW_ENV:
                result["review_env"][key] = content
    for line in lines:
        if line.startswith("apptainer exec") and "gh_broker.py" in line:
            import csv

            broker = shlex.split(line)
            if "--env-file" in broker:
                result["gh_env_file"] = absolute(
                    next(csv.reader([broker[broker.index("--env-file") + 1]]))[0], cwd
                )
    prompt = run / "prompt.txt"
    if prompt.is_file():
        text = read(prompt).decode()
        for label, key in (
            ("Reviewers", "reviewers"),
            ("Target diff", "target-diff"),
            ("Target report", "target-report"),
            ("Requested agents", "agents"),
        ):
            match = re.search(rf"^{label}: (.*)$", text, re.MULTILINE)
            if match:
                options[key] = match[1]
        if "Goal file: /runs/goal.yaml" in text and (run / "goal.yaml").is_file():
            options["goal"] = str(run / "goal.yaml")
    return result


def load(run):
    file = run / "launch.json"
    data = json.loads(read(file)) if file.is_file() else legacy(run)
    if (
        not isinstance(data, dict)
        or data.get("version") != 1
        or not isinstance(data.get("options"), dict)
        or not isinstance(data.get("binds"), list)
        or not all(isinstance(v, str) for v in data["options"].values())
        or not all(isinstance(v, str) for v in data["binds"])
        or not isinstance(data.get("secrets_file"), str)
        or not isinstance(data.get("gh_env_file"), str)
        or not isinstance(data.get("allow_fuse"), bool)
        or not isinstance(data.get("review_env"), dict)
        or any(
            k not in REVIEW_ENV or not isinstance(v, str)
            for k, v in data["review_env"].items()
        )
    ):
        raise ValueError("保存された起動設定が不正です")
    strings = [
        *data["options"].values(),
        *data["binds"],
        data["secrets_file"],
        data["gh_env_file"],
        *data["review_env"].values(),
    ]
    if any("\0" in value for value in strings):
        raise ValueError("設定に NUL 文字は使えません")
    return data


def args(run):
    data = load(run)
    result = []
    for key in VALUE_OPTIONS:
        if key in data["options"]:
            value = data["options"][key]
            if key == "goal" and value and (run / "goal.yaml").is_file():
                value = str(run / "goal.yaml")
            result.extend(["--" + key, value])
    for spec in data["binds"]:
        result.extend(["--bind", spec])
    result.append("--allow-fuse" if data["allow_fuse"] else "--no-allow-fuse")
    result.extend(
        ["--secrets-file", data["secrets_file"]]
        if data["secrets_file"]
        else ["--no-secrets"]
    )
    result.append("--gh-broker" if data["gh_env_file"] else "--no-gh-broker")
    return result


def config_source(run):
    agent = manifest(run)["agent"]
    for path in (
        run / "home" / CONFIG[agent],
        run / "saved_settings" / Path(CONFIG[agent]).name,
        run / "container_config" / Path(CONFIG[agent]).name,
    ):
        if path.is_file() and not path.is_symlink():
            return path
    return None


def config_values(path, data):
    text = data.decode()
    if not text.strip():
        raise ValueError("設定ファイルが空です")
    if path.suffix == ".json":
        values = json.loads(text)
        if not isinstance(values, dict):
            raise ValueError("設定ファイルが JSON オブジェクトではありません")
        return values
    try:
        import tomllib
    except ImportError:
        # Keep the host's Python requirement unchanged; Codex validates TOML itself.
        return {}
    return tomllib.loads(text)


def capture(run):
    if not (run / "session.json").is_file():
        return
    agent = manifest(run)["agent"]
    path = run / "home" / CONFIG[agent]
    if path.is_file() and not path.is_symlink():
        data = read(path, run)
        # Old file-bind setups can leave an empty mount target in the host HOME.
        # Never replace a valid saved configuration with that placeholder.
        config_values(path, data)
        atomic(run / "saved_settings" / path.name, data, run)


def restore(source, destination):
    path = config_source(source)
    if path is None:
        return
    data = read(path, source)
    try:
        config_values(path, data)
    except (ValueError, UnicodeError) as error:
        raise ValueError(
            "保存されたエージェント設定を読めません。--fresh-config で初期設定から再開できます"
        ) from error
    agent = manifest(source)["agent"]
    atomic(destination / "home" / CONFIG[agent], data, destination)
    atomic(destination / "container_config" / path.name, data, destination)


def nul(values):
    for value in values:
        if "\0" in value:
            raise ValueError("設定に NUL 文字は使えません")
        sys.stdout.buffer.write(value.encode() + b"\0")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("save", "args", "env", "broker", "describe", "capture", "restore"),
    )
    parser.add_argument("run", type=Path)
    parser.add_argument("destination", nargs="?", type=Path)
    for key in VALUE_OPTIONS:
        parser.add_argument("--" + key, default="")
    parser.add_argument("--bind", action="append", default=[])
    parser.add_argument("--allow-fuse", action="store_true")
    parser.add_argument("--secrets-file", default="")
    parser.add_argument("--gh-env-file", default="")
    options = parser.parse_args()
    run = options.run.resolve()
    if options.action == "save":
        cwd = Path.cwd()
        values = {key: getattr(options, key.replace("-", "_")) for key in VALUE_OPTIONS}
        for key in ("repo", "goal", "target-diff", "target-report"):
            if values[key]:
                values[key] = absolute(values[key], cwd)
        data = {
            "version": 1,
            "options": values,
            "binds": [bind(value, cwd) for value in options.bind],
            "allow_fuse": options.allow_fuse,
            "secrets_file": options.secrets_file,
            "gh_env_file": options.gh_env_file,
            "review_env": {
                key: os.environ[key] for key in REVIEW_ENV if key in os.environ
            },
        }
        atomic(
            run / "launch.json",
            (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode(),
            run,
        )
        capture(run)
    elif options.action == "args":
        nul(args(run))
    elif options.action == "env":
        nul([part for pair in load(run)["review_env"].items() for part in pair])
    elif options.action == "broker":
        print(load(run)["gh_env_file"])
    elif options.action == "describe":
        if load(run).get("legacy"):
            print(
                "旧形式の実行: 保存済みスクリプトから起動設定を復元（未記録の項目は既定値）"
            )
        path = config_source(run)
        print("エージェント設定: " + (str(path) if path else "現在のリポジトリの設定"))
        if path:
            try:
                values = config_values(path, read(path, run))
                for key in (
                    "model",
                    "effortLevel",
                    "model_reasoning_effort",
                    "theme",
                    "approval_policy",
                    "sandbox_mode",
                ):
                    if key in values:
                        print(
                            "  "
                            + key
                            + ": "
                            + json.dumps(values[key], ensure_ascii=True)
                        )
            except (ValueError, UnicodeError):
                print(
                    "  設定ファイルを解析できません（--fresh-config で初期化できます）"
                )
    elif options.action == "capture":
        capture(run)
    elif options.action == "restore":
        if options.destination is None:
            parser.error("restore requires a destination")
        restore(run, options.destination.resolve())


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as error:
        print("run settings: " + str(error), file=sys.stderr)
        raise SystemExit(2)
