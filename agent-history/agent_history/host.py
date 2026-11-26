"""Which machine the conversations come from, written into each exported note.

The name is the first one set of: export-md --host, AGENT_HISTORY_HOST, the name saved with
`agent-history host set` (kept in the store, so it holds for cron and hooks, which do not read
shell profiles), and this machine's host name. With none of them, notes get no host at all.
"""

from __future__ import annotations

import json
import os
import socket

from .archive import history_root

CONFIG = "config.json"


def load_config():
    try:
        value = json.loads((history_root() / CONFIG).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def save_config(config):
    root = history_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / CONFIG
    temporary = path.with_name("." + CONFIG + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(config, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    temporary.replace(path)


def clean(value):
    return " ".join(str(value).split()) if value is not None else ""


def resolve(argument=None):
    """(name, where it came from); ("", "") when nothing names this machine."""
    for value, source in ((argument, "--host"), (os.environ.get("AGENT_HISTORY_HOST"), "AGENT_HISTORY_HOST"),
                          (load_config().get("host"), "host set")):
        if clean(value):
            return clean(value), source
    try:
        name = clean(socket.gethostname())
    except OSError:
        name = ""
    return (name, "ホスト名") if name else ("", "")


def set_host(name):
    name = clean(name)
    if not name:
        raise ValueError("マシンの名前を指定してください（例: agent-history host set home-wsl）")
    config = load_config()
    config["host"] = name
    save_config(config)
    print(f"このマシンの名前を {name} にしました（書き出すノートの host と host/{name} のタグ）。")
    print("次に export-md を実行すると、書き出し済みのノートにも入ります。")


def unset_host():
    config = load_config()
    if config.pop("host", None) is None:
        print("名前は登録されていません。")
        return
    save_config(config)
    name, source = resolve()
    print(f"登録した名前を消しました。今は {name}（{source}）を使います。" if name else
          "登録した名前を消しました。ノートには host を書きません。")


def show_host():
    name, source = resolve()
    if name:
        print(f"{name}（{source}）")
    else:
        print("名前がありません（ノートには host を書きません）")
