#!/usr/bin/python3
"""Offline GitHub boundary; deliberately echo a synthetic token to test redaction."""

import json
import os
import sys

assert os.environ.get("GH_TOKEN")
assert not os.environ.get("GITHUB_TOKEN")
assert os.environ["GH_PROMPT_DISABLED"] == "1"
assert os.environ["GIT_CONFIG_GLOBAL"] == "/dev/null"
print(
    json.dumps(
        {
            "argv": sys.argv[1:],
            "body": sys.stdin.read(),
            "token": os.environ["GH_TOKEN"],
            "fixture": "GITHUB_BOUNDARY_OK",
        }
    )
)
print(os.environ["GH_TOKEN"], file=sys.stderr)
