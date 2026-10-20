#!/usr/bin/env python3
"""Keep managed worker hooks inert in the isolated reviewer role."""

import os
import runpy
import sys
from pathlib import Path


def main():
    if os.environ.get("AGENTRUN_ROLE") == "reviewer":
        return 0
    if len(sys.argv) != 2:
        raise ValueError("Expected one managed worker hook path")
    target = Path(sys.argv[1]).resolve()
    if (
        target.parent != Path(__file__).resolve().parent
        or target.name == Path(__file__).name
        or target.suffix != ".py"
    ):
        raise ValueError("Hook must be a sibling managed Python script")
    sys.argv = [str(target)]
    runpy.run_path(str(target), run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
