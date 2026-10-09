#!/usr/bin/env python3
"""Readline のファイル名エスケープを解除する。シェルとして評価しない。"""

import os
import shlex
import sys


def decode_path(value):
    # 手入力したスペース・引用符・バックスラッシュを含む実在パスを優先。
    if os.path.exists(os.path.expanduser(value)):
        return value
    try:
        words = shlex.split(value)
    except ValueError:
        return value
    return words[0] if len(words) == 1 else value


if __name__ == "__main__":
    print(os.path.expanduser(decode_path(sys.argv[1])))
