"""Stop hooks that keep the archive current, and their installation into each CLI's settings.

Every time an agent finishes a turn, its Stop hook runs `agent-history hook PROVIDER`.
That reads the transcript path from the hook input, answers at once, and archives the
conversation in a detached process, so the agent never waits for it.

Installation adds one entry to each CLI's hook file and keeps everything else there
(other tools' hooks included); the file is copied to *.agent-history.bak first.
  Claude Code   <claude config>/settings.json       "hooks": {"Stop": [...]}
  Codex         <codex home>/hooks.json             "hooks": {"Stop": [...]}  (Codex asks you to trust it once)
  Antigravity   ~/.gemini/config/hooks.json         {"agent-history": {"Stop": [...]}}
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from .archive import history_root, sync_one
from .sources import PROVIDERS, claude_root, codex_root, remember_workspace, session_for

NAME = "agent-history"
MARK = "-m agent_history hook "  # identifies entries this tool installed
LOG = "hook.log"
LOG_LIMIT = 256 * 1024


def hook_command(provider: str) -> str:
    """The exact command a CLI runs; the package location is fixed at install time."""
    package = Path(__file__).resolve().parent.parent
    return (f"env PYTHONPATH={shlex.quote(str(package))} {shlex.quote(sys.executable)} "
            f"{MARK}{provider}")


def hook_file(provider: str) -> Path:
    if provider == "claude":
        return claude_root() / "settings.json"
    if provider == "codex":
        return codex_root() / "hooks.json"
    return Path.home() / ".gemini/config/hooks.json"


def ours(handler) -> bool:
    return isinstance(handler, dict) and MARK in str(handler.get("command", ""))


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8") or "{}")
    if not isinstance(value, dict):
        raise ValueError(f"{path} が JSON オブジェクトではありません")
    return value


def without_ours(groups: list) -> list:
    """Stop groups minus this tool's handlers; groups left empty by that are dropped."""
    kept = []
    for group in groups:
        if not isinstance(group, dict):
            kept.append(group)
        elif "hooks" in group:  # Claude Code / Codex: {"matcher"?, "hooks": [handlers]}
            handlers = [h for h in group["hooks"] if not ours(h)]
            if handlers or not group["hooks"]:
                kept.append(dict(group, hooks=handlers))
        elif not ours(group):  # Antigravity: handlers directly
            kept.append(group)
    return kept


def installed(provider: str) -> bool:
    data = read_json(hook_file(provider))
    if provider == "antigravity":
        return any(ours(h) for h in (data.get(NAME) or {}).get("Stop", []))
    groups = (data.get("hooks") or {}).get("Stop", [])
    return any(ours(h) for g in groups if isinstance(g, dict) for h in g.get("hooks", []))


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".agent-history.bak"))
    temporary = path.with_name("." + path.name + ".agent-history.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if path.exists():
        os.chmod(temporary, path.stat().st_mode & 0o777)
    temporary.replace(path)


def install(provider: str) -> None:
    path = hook_file(provider)
    data = read_json(path)
    handler = {"type": "command", "command": hook_command(provider), "timeout": 30}
    if provider == "antigravity":
        data[NAME] = {"Stop": [handler]}
    else:
        hooks = data.setdefault("hooks", {})
        if not isinstance(hooks, dict):
            raise ValueError(f"{path} の hooks がオブジェクトではありません")
        hooks["Stop"] = without_ours(hooks.get("Stop", [])) + [{"hooks": [handler]}]
    write(path, data)


def uninstall(provider: str) -> bool:
    path = hook_file(provider)
    if not path.exists() or not installed(provider):
        return False
    data = read_json(path)
    if provider == "antigravity":
        data.pop(NAME, None)
    else:
        groups = without_ours(data["hooks"].get("Stop", []))
        if groups:
            data["hooks"]["Stop"] = groups
        else:
            del data["hooks"]["Stop"]
    write(path, data)
    return True


# --- the hook itself

def transcript_path(provider: str, payload: dict) -> str | None:
    path = payload.get("transcriptPath" if provider == "antigravity" else "transcript_path")
    if isinstance(path, str) and path:
        return path
    ident = payload.get("session_id")
    if provider == "codex" and isinstance(ident, str) and ident:
        # Codex may leave transcript_path empty; its rollout file names end with the session ID.
        found = sorted(codex_root().glob(f"sessions/**/rollout-*{ident}.jsonl"))
        return str(found[-1]) if found else None
    return None


def log(message: str) -> None:
    root = history_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / LOG
    try:
        if path.stat().st_size > LOG_LIMIT:
            path.write_text(path.read_text(encoding="utf-8", errors="replace")[-LOG_LIMIT // 2:])
    except OSError:
        pass
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")


def run_hook(provider: str, stdin) -> int:
    """Answer the CLI at once and archive in the background; never fail the agent's turn."""
    print("{}", flush=True)  # every CLI reads an empty JSON object as "carry on as usual"
    try:
        payload = json.loads(stdin.read() or "{}")
        path = transcript_path(provider, payload if isinstance(payload, dict) else {})
        if not path:
            log(f"{provider}: no transcript path in the Stop hook input")
            return 0
        if provider == "antigravity" and isinstance(payload.get("conversationId"), str) \
                and isinstance(payload.get("cwd"), str) and payload["cwd"]:
            remember_workspace(payload["conversationId"], payload["cwd"])
        subprocess.Popen([sys.executable, "-m", "agent_history", "hook-worker", provider, path],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True,
                         env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent.parent)))
    except Exception as error:  # noqa: BLE001 - a bookkeeping hook must never stop the agent
        log(f"{provider}: {error}")
    return 0


def run_worker(provider: str, path: str) -> int:
    started = time.monotonic()
    try:
        session = session_for(provider, path)
        if session is None:
            log(f"{provider}: not a conversation transcript: {path}")
            return 0
        result = sync_one(session)
        log(f"{provider} {session.session_id}: {result}（{time.monotonic() - started:.1f} 秒）")
    except Exception as error:  # noqa: BLE001 - reported in the log; the agent already moved on
        log(f"{provider} {path}: 保存できませんでした: {error}")
    return 0


def status() -> None:
    for provider in PROVIDERS:
        try:
            state = "登録済み" if installed(provider) else "未登録"
        except (OSError, ValueError) as error:
            state = f"読めません（{error}）"
        print(f"{provider:12s} {state}  {hook_file(provider)}")
