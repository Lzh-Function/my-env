#!/usr/bin/env python3
"""永続セッションの管理。認証情報を含む home 全体は保存しない。"""

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import sys
import time
import unicodedata


MOUNTS = {
    "codex": (".codex/sessions", ".codex/archived_sessions", ".codex/sqlite"),
    "claude": (".claude/projects", ".claude/file-history", ".claude/todos",
               ".claude/tasks", ".claude/plans"),
}
NATIVE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return {}


def manifest(run):
    data = read_json(run / "session.json")
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("保存済みセッション情報がありません（導入前の run は再開できません）")
    if (any(not isinstance(data.get(key), str) for key in ("agent", "repo", "mode", "run_id", "session_key"))
            or data["agent"] not in MOUNTS or not NATIVE_ID.fullmatch(data["session_key"])):
        raise ValueError("セッション情報が不正です")
    return data


def state_dir(run, data):
    return run.parent / ".sessions" / data["session_key"]


def save(run, data):
    tmp = run / "session.json.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(run / "session.json")


def init(run, agent, repo, mode, source=None):
    if agent not in MOUNTS:
        raise ValueError("Unsupported agent: " + str(agent))
    data = {"version": 1, "run_id": run.name, "session_key": run.name, "created_at": time.time(),
            "agent": agent, "repo": str(Path(repo).resolve()), "mode": mode}
    if source:
        old = manifest(source)
        session = discover(source, old)
        if not session:
            raise ValueError("再開可能な会話履歴がありません")
        # 強制終了で finalize が走らなかった元 run の ID もここで確定する。
        old.update(native_id=session["id"], native_cli=session["cli"])
        save(source, old)
        data.update(session_key=old["session_key"], parent_run_id=old["run_id"],
                    native_id=session["id"], native_cli=session["cli"])
    store = state_dir(run, data)
    store.mkdir(parents=True, exist_ok=True, mode=0o700)
    store.chmod(0o700)
    store.parent.chmod(0o700)
    for rel in MOUNTS[agent]:
        (store / rel).mkdir(parents=True, exist_ok=True, mode=0o700)
        # Apptainer の bind 先をあらかじめ作っておく。
        (run / "home" / rel).mkdir(parents=True, exist_ok=True)
    save(run, data)


def jsonl(path, head=False):
    # 大きい履歴でも末尾だけ読む。kill による最後の不完全な行は無視する。
    try:
        with path.open("rb") as stream:
            if head:
                raw = stream.read(65536)
            else:
                size = stream.seek(0, 2)
                stream.seek(max(0, size - 262144))
                if size > 262144:
                    stream.readline()
                raw = stream.read()
        for line in raw.splitlines():
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    yield value
            except (ValueError, UnicodeError):
                continue
    except OSError:
        return


def text_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part.get("text", "") for part in content
                         if isinstance(part, dict) and part.get("type", "text")
                         in ("text", "input_text", "output_text"))
    return ""


def messages(path, cli):
    result = []
    for entry in jsonl(path):
        if not isinstance(entry, dict):
            continue
        if cli == "codex":
            # event_msg と response_item は重複するので、正式な message のみ使う。
            if entry.get("type") != "response_item":
                continue
            item = entry.get("payload", {})
        else:
            item = entry.get("message", entry)
        if not isinstance(item, dict):
            continue
        role = item.get("role", entry.get("type", ""))
        if role not in ("user", "assistant"):
            continue
        if cli == "codex" and (item.get("type", "message") != "message"
                               or item.get("phase") == "analysis" or item.get("channel") == "analysis"):
            continue
        text = text_content(item.get("content", item.get("text", "")))
        if text.strip():
            result.append({"role": role, "text": text})
    return result[-6:]


def discover(run, data, latest=False):
    store = state_dir(run, data)
    agent = data["agent"]
    candidates = []
    if agent == "codex":
        paths = store.glob(".codex/*sessions/**/*.jsonl")
        cli = "codex"
    elif agent == "claude":
        paths = store.glob(".claude/projects/*/*.jsonl")
        cli = "claude"
    else:
        raise ValueError("Unsupported agent: " + str(agent))
    for path in paths:
        ident = ""
        for entry in jsonl(path, head=True):
            if cli == "codex" and entry.get("type") == "session_meta":
                meta = entry.get("payload", {})
                ident = meta.get("id", meta.get("session_id", "")) if isinstance(meta, dict) else ""
                break
            if cli == "claude" and entry.get("sessionId"):
                ident = entry["sessionId"]
                break
        if isinstance(ident, str) and NATIVE_ID.fullmatch(ident):
            candidates.append({"id": ident, "cli": cli, "path": path,
                               "mtime": path.stat().st_mtime})
    if latest and data.get("native_id"):
        candidates = [c for c in candidates if c["mtime"] >= data.get("created_at", 0)
                      or (c["id"] == data["native_id"] and c["cli"] == data["native_cli"])]
    elif data.get("native_id"):
        candidates = [c for c in candidates if c["id"] == data["native_id"]
                      and c["cli"] == data["native_cli"]]
    if not candidates:
        return None
    selected = max(candidates, key=lambda c: c["mtime"])
    selected["messages"] = messages(selected["path"], selected["cli"])
    return selected


def safe_text(text):
    # 会話中の ANSI/制御コードを端末コマンドとして実行させない。
    return "".join(c for c in text if c == "\n" or not unicodedata.category(c).startswith("C"))


def describe(run):
    try:
        data = manifest(run)
        session = discover(run, data)
        reason = "再開可能" if session else "会話履歴なし"
        recent = session["messages"] if session else []
        snippet = (recent[-1]["role"] + ": " + recent[-1]["text"]) if recent else "末尾の発言なし"
        return data, session, f'{safe_text(data["run_id"])}  {data["agent"]}  [{reason}]  ' + " ".join(safe_text(snippet).split())[:120]
    except (ValueError, OSError, TypeError, AttributeError) as error:
        return None, None, f"{safe_text(run.name)}  [再開不可: {safe_text(str(error))}]"


def runs(parent):
    return sorted((p for p in parent.iterdir() if p.is_dir() and not p.is_symlink()
                   and not p.name.startswith(".")), key=lambda p: p.name, reverse=True) if parent.is_dir() else []


def resolve(parent, target):
    path = Path(target)
    if path.is_dir():
        return path.resolve()
    if (parent / target).is_dir():
        return (parent / target).resolve()
    matches = []
    for path in runs(parent):
        data = read_json(path / "session.json")
        if isinstance(data, dict) and data.get("run_id") == target:
            matches.append(path)
    if len(matches) == 1:
        return matches[0]
    raise ValueError("run ID が見つかりません: " + target)


def command(run):
    data = manifest(run)
    ident = data.get("native_id")
    cli = data.get("native_cli")
    if cli != data["agent"]:
        raise ValueError("Session CLI does not match its agent")
    if not ident or not NATIVE_ID.fullmatch(ident):
        raise ValueError("再開用の会話 ID がありません")
    if cli == "codex":
        cmd = ["codex", "resume", ident, "--dangerously-bypass-approvals-and-sandbox",
               "--dangerously-bypass-hook-trust", "--cd", "/workspace",
               "-c", 'sqlite_home="/home/sandbox/.codex/sqlite"']
    elif cli == "claude":
        cmd = ["claude", "--resume", ident, "--dangerously-skip-permissions"]
    else:
        raise ValueError("未対応の CLI: " + str(cli))
    return "cd /workspace && " + shlex.join(cmd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "mounts", "command", "finalize", "list", "pick", "choices", "resolve", "preview", "fields"))
    parser.add_argument("path", type=Path)
    parser.add_argument("args", nargs="*")
    args = parser.parse_args()
    run = args.path.resolve()
    if args.action == "init":
        init(run, *args.args[:3], source=Path(args.args[3]).resolve() if len(args.args) > 3 else None)
    elif args.action == "mounts":
        data = manifest(run) if (run / "session.json").is_file() else {
            "agent": args.args[0], "session_key": run.name}
        for rel in MOUNTS[data["agent"]]:
            print(str(state_dir(run, data) / rel) + "\t/home/sandbox/" + rel)
    elif args.action == "command":
        print(command(run))
    elif args.action == "finalize":
        data = manifest(run)
        session = discover(run, data, latest=True)
        if session:
            data.update(native_id=session["id"], native_cli=session["cli"])
            save(run, data)
    elif args.action == "fields":
        data = manifest(run)
        if not discover(run, data):
            raise ValueError("再開可能な会話履歴がありません")
        for key in ("agent", "repo", "mode"):
            value = data[key]
            if "\n" in value or "\r" in value:
                raise ValueError("セッション情報に不正な改行があります")
            print(value)
    elif args.action == "resolve":
        print(resolve(run, args.args[0]))
    elif args.action == "preview":
        data, session, label = describe(run)
        print(label)
        for item in session["messages"] if session else []:
            print("\n[" + item["role"] + "]\n" + safe_text(item["text"]))
    elif args.action == "list":
        for path in runs(run):
            print(describe(path)[2])
    elif args.action in ("pick", "choices"):
        candidates = [(p, describe(p)) for p in runs(run)]
        candidates = [(p, info) for p, info in candidates if info[1]]
        if not candidates:
            raise ValueError("再開可能な run がありません。導入後に開始した会話が対象です")
        if args.action == "choices":
            for _, info in candidates:
                print(info[2])
            return
        if not sys.stdin.isatty():
            raise ValueError("選択には端末が必要です。resume --list または resume RUN_ID を使ってください")
        for n, (_, info) in enumerate(candidates, 1):
            print(f"{n:>3}. {info[2]}", file=sys.stderr)
        while True:
            print("番号または run ID（q で終了）: ", end="", file=sys.stderr, flush=True)
            answer = sys.stdin.readline().strip()
            if not answer or answer == "q":
                raise ValueError("選択を中止しました")
            for n, (path, info) in enumerate(candidates, 1):
                if answer in (str(n), info[0]["run_id"], path.name):
                    print(path)
                    return
            print("一覧の番号か run ID を入力してください", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        print("resume: " + safe_text(str(error)), file=sys.stderr)
        sys.exit(2)
