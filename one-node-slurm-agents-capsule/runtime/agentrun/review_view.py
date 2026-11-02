#!/usr/bin/env python3
"""相互監査の一覧と対話を、ホストの端末で読みやすく表示する（読み取りのみ）。"""

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import sys
import time
import unicodedata

TERMINAL = {"success", "failed", "cancelled", "timeout"}
# 新しいラウンドは reviews/<thread>/<review> に置かれる。状態ファイルの値はこの形だけを信用する。
DIRECTORY = re.compile(r"thread-[0-9a-f]+/review-[0-9a-f]+")
# これらの失敗は、同じラウンドがreview_retryで再開されうる。
RETRYABLE = {"invalid_model", "authentication", "rate_limit"}
# 監査担当の出力は信頼できないため、端末を操作できる制御文字を表示前に除く。
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def clean(value):
    return CONTROL.sub("", str(value))


def pad(value, width):
    """全角文字を2桁として数え、端末上の列を揃える。"""
    text = clean(value)
    used = sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)
    return text + " " * max(0, width - used)


def stamp(value):
    return datetime.fromtimestamp(value).strftime("%m-%d %H:%M:%S") if isinstance(value, (int, float)) else "-"


def load_threads(run):
    """スレッドを開始順に並べ、ユーザーが指定しやすい通し番号を付ける。"""
    rounds = []
    reviews = run / "reviews"
    for path in [*reviews.glob("review-*/state.json"), *reviews.glob("thread-*/review-*/state.json")]:
        try:
            state = json.loads(path.read_text())
        except (OSError, ValueError):
            continue  # 書き込み途中の状態は次回の読み込みで扱う。
        if isinstance(state, dict) and isinstance(state.get("review_id"), str) \
                and isinstance(state.get("review_thread_id"), str):
            rounds.append(state)
    threads = {}
    for state in sorted(rounds, key=lambda s: (s.get("created_at") or 0, s.get("round") or 0)):
        threads.setdefault(state["review_thread_id"], []).append(state)
    return [{"number": number, "id": ident, "provider": states[0].get("provider", "-"), "rounds": states}
            for number, (ident, states) in enumerate(threads.items(), 1)]


def activity(thread):
    """最新ラウンドの状態から、進行中・再試行待ち・終了を判定する。"""
    latest = thread["rounds"][-1]
    status = latest.get("status")
    if status not in TERMINAL:
        return "進行中（回答待ち）" if status == "waiting_reply" else "進行中"
    if status == "failed" and latest.get("error_kind") in RETRYABLE:
        return "再試行待ち"
    return "終了"


def is_active(thread):
    return activity(thread) != "終了"


def model_label(state):
    selection = state.get("model_selection") or {}
    model = state.get("model_used") or selection.get("model") or "CLI既定"
    effort = selection.get("effort")
    return f"{model}{'/' + effort if effort else ''} ({selection.get('model_source', 'cli_default')})"


def label(thread):
    return f"{clean(thread['provider'])}#{thread['number']}"


def show_list(run, threads):
    if not threads:
        print(f"{run.name}: 相互監査の記録はありません")
        return
    active = sum(is_active(t) for t in threads)
    print(f"{run.name} の相互監査（{len(threads)}スレッド、進行中 {active}）")
    print(f"{'No':>3}  {pad('reviewer', 12)} {pad('state', 18)} {'rounds':>6}  {pad('latest', 24)} {pad('started', 15)} model")
    for thread in threads:
        latest = thread["rounds"][-1]
        result = latest.get("verdict") or latest.get("status", "-")
        if latest.get("status") == "failed" and latest.get("error_kind"):
            result = "failed:" + latest["error_kind"]
        print(f"{thread['number']:>3}  {pad(thread['provider'], 12)} {pad(activity(thread), 18)} "
              f"{len(thread['rounds']):>6}  {pad(result, 24)} {pad(stamp(thread['rounds'][0].get('created_at')), 15)} "
              f"{clean(model_label(latest))}")
    print()
    print("対話を表示:           agentrun reviews <No>")
    print("進行中だけを追跡:     agentrun reviews --follow   （--reviewer NAME で絞り込み）")


def select(threads, query, reviewer):
    if reviewer:
        threads = [t for t in threads if t["provider"] == reviewer]
    if query is None:
        return threads
    if query.isdigit():
        chosen = [t for t in threads if t["number"] == int(query)]
    else:
        # スクリプト等から使う場合のため、thread・reviewのIDの先頭一致も受け付ける。
        key = query.removeprefix("thread-").removeprefix("review-")
        chosen = [t for t in threads if t["id"].removeprefix("thread-").startswith(key)
                  or any(s["review_id"].removeprefix("review-").startswith(key) for s in t["rounds"])]
    if len(chosen) != 1:
        raise ValueError(("該当する監査がありません: " if not chosen
                          else "候補が複数あります。番号で指定してください: ") + query)
    return chosen


def indent(text, prefix="    "):
    return "\n".join(prefix + line for line in clean(text).splitlines() or [""])


def render(event, prefix=""):
    kind, payload = event.get("kind"), event.get("payload") or {}
    lines = [f"[{stamp(event.get('timestamp'))}] {prefix}{clean(event.get('sender'))} → "
             f"{clean(event.get('recipient'))}: {clean(kind)}"]
    if kind == "question":
        for question in payload.get("questions", []):
            lines.append(indent(f"Q {question.get('question_id')}: {question.get('text', '')}"))
            if question.get("evidence"):
                lines.append(indent("根拠: " + ", ".join(map(str, question["evidence"])), "      "))
    elif kind == "answer":
        for answer in payload.get("answers", []):
            lines.append(indent(f"A {answer.get('question_id')}: {answer.get('answer', '')}"))
            if answer.get("evidence"):
                lines.append(indent("根拠: " + ", ".join(map(str, answer["evidence"])), "      "))
        if payload.get("include"):
            lines.append(indent("追加した資料: " + ", ".join(map(str, payload["include"]))))
    elif kind == "review_result":
        lines.append(indent(f"判定: {payload.get('verdict')} / 確認範囲: {payload.get('coverage')}"))
        if payload.get("summary"):
            lines.append(indent(payload["summary"]))
        for finding in payload.get("findings", []):
            lines.append(indent(f"- [{finding.get('severity')}] {finding.get('finding_id')} "
                                f"{finding.get('file')}:{finding.get('line')} {finding.get('message', '')}"))
            if finding.get("suggestion"):
                lines.append(indent("提案: " + finding["suggestion"], "        "))
        for item in payload.get("prior_dispositions", []):
            lines.append(indent(f"- 前回 {item.get('finding_id')}: {item.get('status')} — {item.get('reason', '')}"))
        for limitation in payload.get("limitations", []):
            lines.append(indent("制約: " + limitation))
    elif kind == "response":
        for item in payload.get("responses", []):
            lines.append(indent(f"- {item.get('finding_id')}: {item.get('action')} — {item.get('reason', '')}"))
    elif kind == "repair" and payload.get("error"):
        lines.append(indent("出力の修正を依頼: " + payload["error"]))
    elif kind == "new_session" and payload.get("error"):
        lines.append(indent("以前の会話を再開できないため新しい会話で実施: " + payload["error"]))
    elif kind in ("failed", "timeout", "cancelled") and payload.get("error"):
        lines.append(indent("エラー: " + payload["error"]))
    elif kind == "model_retry" and payload:
        lines.append(indent(f"モデル: {payload.get('model') or 'CLI既定'} / effort: {payload.get('effort') or 'CLI既定'}"))
    return "\n".join(lines)


def events(run, state):
    directory = state.get("directory")
    if not (isinstance(directory, str) and DIRECTORY.fullmatch(directory)):
        directory = state["review_id"]
    try:
        lines = (run / "reviews" / directory / "events.jsonl").read_text().splitlines()
    except OSError:
        return []
    records = []
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue  # 書き込み途中の末尾行は次回の読み込みで表示する。
        if isinstance(record, dict):
            records.append(record)
    return records


def emit(run, threads, printed, prefixed):
    """未表示のイベントを時刻順に出力する。prefixedなら各行に監査担当と番号を付ける。"""
    pending = []
    for thread in threads:
        for state in thread["rounds"]:
            seen = printed.get(state["review_id"], 0)
            pending += [(record.get("timestamp") or 0, thread["number"], index, thread, state, record)
                        for index, record in enumerate(events(run, state)[seen:], seen)]
    for _, _, index, thread, state, record in sorted(pending, key=lambda item: item[:3]):
        prefix = label(thread) + " " if prefixed else ""
        if state["review_id"] not in printed:
            print(f"\n=== {label(thread)} ラウンド {state.get('round')} — {clean(model_label(state))} ===")
        print(render(record, prefix), flush=True)
        printed[state["review_id"]] = index + 1


def show(run, query, reviewer):
    threads = select(load_threads(run), query, reviewer)
    if not threads:
        print("該当する監査はありません")
    for thread in threads:
        emit(run, [thread], {}, prefixed=False)
        print(f"\n（{label(thread)}: {activity(thread)}）")


def follow(run, query, reviewer, interval=1.0):
    printed, watching, announced = {}, set(), False
    while True:
        threads = select(load_threads(run), query, reviewer)
        if query is None:
            # 進行中のスレッドだけを追う。再確認で再開したスレッドは再び加わる。
            current = [t for t in threads if is_active(t) or t["id"] in watching]
        else:
            current = threads
        for thread in current:
            if thread["id"] not in watching:
                watching.add(thread["id"])
                print(f"\n>>> {label(thread)} を追跡します（{activity(thread)}）", flush=True)
        emit(run, current, printed, prefixed=query is None)
        for thread in current:
            if not is_active(thread):
                latest = thread["rounds"][-1]
                print(f"\n<<< {label(thread)} が終了しました: {clean(latest.get('verdict') or latest.get('status'))}",
                      flush=True)
                watching.discard(thread["id"])
                if query is not None:
                    return
        if query is None and not watching and not announced:
            print("\n進行中の監査はありません。新しい監査の開始を待っています（Ctrl+Cで終了）", flush=True)
            announced = True
        elif watching:
            announced = False
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("review", nargs="?", help="一覧の番号（またはIDの先頭）")
    parser.add_argument("--follow", action="store_true")
    parser.add_argument("--reviewer", choices=("codex", "claude", "antigravity"))
    args = parser.parse_args()
    run = args.run.resolve()
    try:
        if args.follow:
            follow(run, args.review, args.reviewer)
        elif args.review is None and args.reviewer is None:
            show_list(run, load_threads(run))
        else:
            show(run, args.review, args.reviewer)
    except KeyboardInterrupt:
        return 130
    except ValueError as error:
        print(clean(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
