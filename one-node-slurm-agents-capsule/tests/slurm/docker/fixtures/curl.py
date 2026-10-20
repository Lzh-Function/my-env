#!/usr/bin/env python3
"""Only the installer HTTP boundary is replaced; Slurm/Apptainer stay real."""

import json
import sys
from pathlib import Path

args = sys.argv[1:]
urls = [arg for arg in args if arg.startswith("https://")]
known = {
    "https://chatgpt.com/codex/install.sh": "codex",
    "https://claude.ai/install.sh": "claude",
}
if len(urls) != 1 or urls[0] not in known or "-o" not in args:
    raise SystemExit("test curl refuses unexpected network requests")
cli = known[urls[0]]
contract = {
    "claude": '[ "$#" -eq 1 ] && [ "$1" = latest ]\n',
    "codex": '[ "$CODEX_RELEASE" = latest ] && [ "$CODEX_NON_INTERACTIVE" = 1 ]\n'
    '[ "$CODEX_INSTALL_DIR" = "$HOME/.local/bin" ]\n',
}[cli]
scenario = Path("/workspace/.capsule-test.json")
options = json.loads(scenario.read_text()) if scenario.exists() else {}
if options.get("download_failure"):
    print("synthetic DNS failure", file=sys.stderr)
    raise SystemExit(6)
Path(args[args.index("-o") + 1]).write_text(
    "#!/bin/sh\nexit 42\n"
    if options.get("installer_failure")
    else '#!/bin/sh\nset -eu\n[ "$HOME" != /home/sandbox ]\n[ "$PWD" = "$HOME" ]\n'
    + contract
    + 'mkdir -p "$HOME/.local/bin"\n'
    f'cp /opt/capsule-test/agent.py "$HOME/.local/bin/{cli}"\n'
    f'chmod 755 "$HOME/.local/bin/{cli}"\n'
)
