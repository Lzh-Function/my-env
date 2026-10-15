#!/usr/bin/env python3
"""wizard の前回値を保存する。シェルコードとして評価しない。"""

import json
from pathlib import Path
import re
import shlex
import sys


def main():
    action, filename, *args = sys.argv[1:]
    path = Path(filename)
    if action == "load":
        if not path.is_file():
            return
        raw = path.read_text(encoding="utf-8")
        if raw.lstrip().startswith("{"):
            data = json.loads(raw)
        else:
            # 移植元の key=value 形式も読めるようにする。
            data = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
            data["bind"] = shlex.split(data.pop("binds", ""))
        for key, value in data.items():
            if not re.fullmatch(r"[a-z_]+", key):
                continue
            for item in value if isinstance(value, list) else [value]:
                if isinstance(item, str) and "\0" not in item:
                    sys.stdout.buffer.write(key.encode() + b"\0" + item.encode() + b"\0")
    elif action == "save":
        data = {"bind": []}
        for key, value in zip(args[::2], args[1::2]):
            if key == "bind":
                data["bind"].append(value)
            else:
                data[key] = value
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = path.with_name(path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as stream:
            tmp.chmod(0o600)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        tmp.replace(path)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError, AttributeError) as error:
        print(f"wizard defaults: {error}", file=sys.stderr)
        sys.exit(1)
