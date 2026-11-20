"""agent-history: keep, search and export the conversations of local Claude Code, Codex and Antigravity."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import hooks
from .archive import history_root, sync
from .index import connect, conversations, export_markdown, rename, show
from .sources import PROVIDERS

USAGE_EPILOG = """使い方の例:
  agent-history sync                         # ローカルの会話をまとめて保存（変わったものだけ）
  agent-history list                         # 最近の会話の一覧
  agent-history search 語...                  # 全文検索（すべての語を含む会話）
  agent-history export-md ~/vault/agents     # Obsidian 向けに 1 会話 1 ノートで書き出す
  agent-history rename ID 新しい名前          # 会話に名前を付ける（--clear で元に戻す）
  agent-history hooks install                # Stop フックを各 CLI に登録し、返答ごとに自動保存
"""


def parser():
    top = argparse.ArgumentParser(prog="agent-history", description=__doc__, epilog=USAGE_EPILOG,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = top.add_subparsers(dest="command", required=True)

    def filters(p, project=True):
        p.add_argument("--agent", choices=PROVIDERS, help="この CLI の会話だけ")
        if project:
            p.add_argument("--project", default="", help="作業ディレクトリのパスにこの文字列を含む会話だけ")
            p.add_argument("--no-sync", action="store_true", help="先に保存し直さない（保存済みの内容だけを使う）")

    p = sub.add_parser("sync", help="ローカルの会話を保存する（変わったものだけ）")
    filters(p, project=False)
    p.add_argument("--force", action="store_true", help="変わっていない会話も作り直す")
    p = sub.add_parser("list", help="会話の一覧（最後に動いた順）")
    filters(p)
    p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("search", help="全文検索")
    p.add_argument("words", nargs="+")
    filters(p)
    p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("export-md", help="Obsidian 向けの Markdown に書き出す")
    p.add_argument("directory", type=Path)
    filters(p)
    p = sub.add_parser("rename", help="会話に名前を付ける")
    p.add_argument("ident", metavar="ID")
    p.add_argument("name", nargs="*")
    p.add_argument("--clear", action="store_true", help="付けた名前を消し、CLI の付けた名前に戻す")
    p = sub.add_parser("hooks", help="Stop フック（返答ごとの自動保存）の登録・解除・状態")
    p.add_argument("action", choices=("install", "uninstall", "status"))
    p.add_argument("--agent", choices=PROVIDERS, action="append", help="対象の CLI（省略時は 3 つとも）")
    p = sub.add_parser("hook", help=argparse.SUPPRESS)
    p.add_argument("provider", choices=PROVIDERS)
    p = sub.add_parser("hook-worker", help=argparse.SUPPRESS)
    p.add_argument("provider", choices=PROVIDERS)
    p.add_argument("transcript")
    return top


def report(counts):
    failed = f"、失敗 {counts['failed']} 件" if counts["failed"] else ""
    print(f"保存しました: 新規 {counts['new']} 件、更新 {counts['updated']} 件、変更なし {counts['same']} 件{failed}"
          f" → {history_root()}")


def main(argv=None):
    options = parser().parse_args(argv)
    if options.command == "hook":
        return hooks.run_hook(options.provider, sys.stdin)
    if options.command == "hook-worker":
        return hooks.run_worker(options.provider, options.transcript)
    if options.command == "hooks":
        targets = options.agent or list(PROVIDERS)
        if options.action == "status":
            hooks.status()
        elif options.action == "install":
            for provider in targets:
                hooks.install(provider)
                print(f"{provider}: 登録しました（{hooks.hook_file(provider)}、元の内容は .agent-history.bak）")
            if "codex" in targets:
                print("Codex は新しいフックを信頼するか、次の起動時に確認します。承認すると動き始めます。")
        else:
            for provider in targets:
                done = hooks.uninstall(provider)
                print(f"{provider}: " + ("解除しました" if done else "登録されていません"))
        return 0
    providers = [options.agent] if getattr(options, "agent", None) else list(PROVIDERS)
    if options.command == "sync":
        report(sync(providers, force=options.force))
        return 0
    if not getattr(options, "no_sync", False):
        sync(providers, quiet=True)
    db = connect()
    if db is None:
        print(f"保存された会話はまだありません（{history_root()}）。")
        return 0
    try:
        if options.command == "rename":
            found = conversations(db) + conversations(db, noise=True)
            rename(found, options.ident, " ".join(options.name), options.clear)
            return 0
        words = options.words if options.command == "search" else ()
        found = conversations(db, words, options.agent, options.project)
        if options.command == "export-md":
            hidden = conversations(db, (), options.agent, options.project, noise=True)
            export_markdown(found, options.directory.expanduser().resolve(), hidden)
        else:
            if options.limit < 1:
                raise ValueError("--limit は 1 以上にしてください")
            show(found, words, options.limit)
    finally:
        db.close()
    return 0


def entry():
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        print(f"agent-history: {error}", file=sys.stderr)
        sys.exit(2)
