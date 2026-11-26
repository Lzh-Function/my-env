# wizard の入口（起動か、それ以外か）と「その他の機能」メニュー（agentrun から source する）。
# 各機能は既存のサブコマンドを別プロセスの agentrun として呼ぶ。失敗や exit があっても wizard は続き、
# Ctrl+C はそのコマンドだけを止めてメニューに戻る。
WIZARD_TOP_LAUNCH='agentrun を起動する（新規・会話の再開）'
WIZARD_TOP_TOOLS='その他の機能（実行中の一覧、ログ、会話履歴、テンプレート、認証、点検など）'
WIZARD_DRY_RUN=0 WIZARD_FROM_MENU=0 WIZARD_DONE=0
WIZARD_EXPORT_DIR_FILE="$HOME/.agentrun/wizard-export-dir"

# Return codes inside menus: 0 = done (stay in this menu), 10 = back, 130 = cancel the wizard.
wizard_menu_rc() {
    case "$1" in 0|1|10) return 0 ;; *) return "$1" ;; esac
}

wizard_pause() {
    local answer
    wizard_readline_keys
    read -e -r -p 'Enter でメニューに戻る (:back=戻る, :cancel=キャンセル): ' answer || return 130
    [ "$answer" != :cancel ] && [ "$answer" != $'\e' ] || return 130
    return 0
}

# Run one agentrun command with its output on the terminal, then wait before redrawing the menu.
wizard_exec() {
    local title="$1" rc=0
    shift
    printf '\n\033[1;35m== %s ==\033[0m\n' "$title"
    # A caught trap is reset to the default in the subshell, so Ctrl+C stops only the command.
    trap ':' INT
    ( trap - INT TERM; "$@" ) || rc=$?
    trap wizard_abort INT TERM
    if [ "$rc" -eq 0 ]; then printf '\n\033[1;32m完了しました。\033[0m\n'
    elif [ "$rc" -eq 130 ]; then printf '\n中断しました。\n'
    else printf '\n\033[1;31m終了コード %s で終わりました（上の表示を確認してください）。\033[0m\n' "$rc"; fi
    wizard_pause
}

# Each feature runs as a separate agentrun process: a function called inside the menu's `|| rc=$?`
# would run with errexit ignored, which the subcommands rely on to stop at the first error.
wizard_cli() {
    "$ROOT_DIR/runtime/agentrun/agentrun" "$@"
}

wizard_python() {
    python3 "$ROOT_DIR/runtime/agentrun/$1" "${@:2}"
}

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

command_wizard() {
    [ -t 0 ] && [ -t 1 ] || { printf 'agentrun wizard requires an interactive terminal\n' >&2; return 1; }
    detect_wizard_ui
    trap wizard_abort INT TERM
    # Launch options on the command line mean "launch"; skip the first menu.
    if [ "$#" -gt 0 ]; then wizard_launch "$@"; return; fi
    local choice rc
    while :; do
        WIZARD_DRY_RUN=0 WIZARD_FROM_MENU=1 WIZARD_DONE=0 rc=0
        choice="$(wizard_select 'agentrun wizard — 何をしますか？' "$WIZARD_TOP_LAUNCH" "$WIZARD_TOP_TOOLS")" || rc=$?
        case "$rc" in
            0) ;;
            10) trap - INT TERM; printf 'wizard を終了しました\n' >&2; return 0 ;;
            *) wizard_abort ;;
        esac
        rc=0
        case "$choice" in
            "$WIZARD_TOP_LAUNCH") wizard_launch || rc=$? ;;
            *) wizard_tools || rc=$? ;;
        esac
        case "$rc" in
            10) continue ;;
            130) wizard_abort ;;
        esac
        [ "$rc" -eq 0 ] && [ "$WIZARD_DONE" -eq 0 ] && [ "$choice" != "$WIZARD_TOP_LAUNCH" ] && continue
        trap - INT TERM
        return "$rc"
    done
}

wizard_tools() {
    local ps='実行中の agentrun を見る（ジョブごと、overlap 関係つき）'
    local hold='確保ジョブ（ノードを確保して、その中でセッションを動かす：作る・状態・1 つ止める・解放）'
    local runs='run を選んで、状態・ログ・成果物・相互監査を見る'
    local history='会話履歴（一覧・検索・Obsidian などへの書き出し）'
    local templates='テンプレートの管理（run から登録・中身の確認・削除）'
    local auth='認証（状態の確認・ログイン・取り込み・リセット）'
    local dry='起動せずに、起動内容だけ確認する（dry-run）'
    local check='環境の点検と設定（doctor・validate・smoke-test など）'
    local extend='スキルの追加と目標ファイルの作成'
    local choice rc
    while :; do
        rc=0
        choice="$(wizard_select 'その他の機能 — どれを使いますか？' "$ps" "$runs" "$history" "$templates" "$auth" "$dry" "$check" "$extend" "$hold")" || rc=$?
        [ "$rc" -eq 0 ] || { [ "$rc" -eq 10 ] && return 0; return "$rc"; }
        case "$choice" in
            "$ps") wizard_exec '実行中の agentrun' wizard_python active.py || rc=$? ;;
            "$hold") wizard_hold || rc=$? ;;
            "$runs") wizard_runs || rc=$? ;;
            "$history") wizard_history || rc=$? ;;
            "$templates") wizard_template_manage || rc=$?; WIZARD_TEMPLATE_CACHE='' ;;
            "$auth") wizard_auth || rc=$? ;;
            "$dry")
                WIZARD_DRY_RUN=1
                wizard_launch || rc=$?
                WIZARD_DRY_RUN=0
                [ "$WIZARD_DONE" -eq 0 ] || return "$rc" ;;
            "$check") wizard_checks || rc=$? ;;
            "$extend") wizard_extend || rc=$? ;;
        esac
        wizard_menu_rc "$rc" || return $?
    done
}

# ---------------------------------------------------------------------------
# Hold job: an idle job that keeps the node; sessions run inside it as steps
# ---------------------------------------------------------------------------

wizard_hold() {
    local status='確保ジョブの状態と、載っているセッションを見る'
    local start='確保ジョブを作る（パーティションのノード全体を確保）'
    local cancel='確保ジョブの中のセッションを 1 つ止める（ほかはそのまま）'
    local stop='確保ジョブを解放する（載っているセッションも終わります）'
    local choice rc
    while :; do
        rc=0
        choice="$(wizard_select '確保ジョブ — どうしますか？（確保ジョブがある間、assist・resume・--submit はその中で起動します）' \
            "$status" "$start" "$cancel" "$stop")" || rc=$?
        [ "$rc" -eq 0 ] || { [ "$rc" -eq 10 ] && return 0; return "$rc"; }
        case "$choice" in
            "$status") wizard_exec '確保ジョブの状態' wizard_cli hold status || rc=$? ;;
            "$start")
                local WIZARD_NEW_HOLD_PARTITION="${AGENTRUN_SLURM_PARTITION:-}" WIZARD_NEW_HOLD_TIME='' WIZARD_NEW_HOLD_INFO=''
                local -a hold_args=()
                wizard_new_hold || rc=$?
                if [ "$rc" -eq 0 ]; then
                    hold_args=(--partition "$WIZARD_NEW_HOLD_PARTITION")
                    [ -z "$WIZARD_NEW_HOLD_TIME" ] || hold_args+=(--time "$WIZARD_NEW_HOLD_TIME")
                    if wizard_confirm "${WIZARD_NEW_HOLD_INFO}"$'\n'"確保する時間: ${WIZARD_NEW_HOLD_TIME:-パーティションの上限}"$'\n'"この確保ジョブを作りますか？" 1; then
                        wizard_exec '確保ジョブを作る' wizard_cli hold start "${hold_args[@]}" || rc=$?
                    else rc=$?; [ "$rc" -eq 1 ] && rc=0; fi
                elif [ "$rc" -eq 11 ]; then rc=0; fi ;;
            "$cancel")
                local WIZARD_RUN=''
                wizard_pick_run || rc=$?
                [ "$rc" -ne 0 ] || [ -z "$WIZARD_RUN" ] || {
                    if wizard_confirm "$(basename "$WIZARD_RUN") を止めますか？" 0; then
                        wizard_exec 'セッションを止める' wizard_cli hold cancel "$WIZARD_RUN" || rc=$?
                    else rc=$?; [ "$rc" -eq 1 ] && rc=0; fi
                } ;;
            "$stop") wizard_exec '確保ジョブを解放する' wizard_cli hold stop || rc=$? ;;
        esac
        wizard_menu_rc "$rc" || return $?
    done
}

# ---------------------------------------------------------------------------
# Runs: pick one, then act on it
# ---------------------------------------------------------------------------

wizard_pick_run() {
    # Sets WIZARD_RUN to the chosen run directory.
    local -a paths=() labels=()
    local path text choice index
    while IFS=$'\t' read -r path text; do
        [ -n "$path" ] || continue
        paths+=("$path") labels+=("$text")
    done < <(wizard_python run_menu.py runs "$PWD" 2>/dev/null)
    if [ "${#paths[@]}" -eq 0 ]; then
        wizard_banner "run が見つかりません（$PWD/.agent-runs と、起動中の run の登録簿を探しました）。run を起動したディレクトリで wizard を開いてください。" || return $?
        return 10
    fi
    choice="$(wizard_select 'どの run を見ますか？（新しい順。別ディレクトリの run は括弧内にプロジェクト名）' "${labels[@]}")" || return $?
    for index in "${!labels[@]}"; do
        [ "${labels[index]}" != "$choice" ] || { WIZARD_RUN="${paths[index]}"; return 0; }
    done
    return 10
}

wizard_runs() {
    local rc=0 WIZARD_RUN=''
    while :; do
        rc=0
        wizard_pick_run || rc=$?
        [ "$rc" -eq 0 ] || { [ "$rc" -eq 10 ] && return 0; return "$rc"; }
        wizard_run_actions "$WIZARD_RUN" || rc=$?
        wizard_menu_rc "$rc" || return $?
    done
}

wizard_run_actions() {
    local run="$1" choice rc summary
    local logs='ログを見る' status='status.json を見る' verify='成果物を点検する（verify-run）'
    local reviews='相互監査の一覧と対話を見る' follow='相互監査を追いかけて表示する（Ctrl+C で戻る）'
    local export='会話履歴を今すぐ保存し直す（保存に失敗したときや、最新の内容で上書きしたいとき）'
    local watch='バッチジョブの終了を待って会話履歴を回収する（回収がまだ終わっていないバッチ run）'
    local template='この run の設定をテンプレートとして保存する'
    local resume='この run の会話を再開する（設定を確認してから新しいジョブで対話再開）'
    while :; do
        rc=0
        summary="$(wizard_python run_menu.py summary "$run" 2>&1)" || summary="$run"
        local -a options=()
        if wizard_python run_menu.py resumable "$run"; then options+=("$resume"); fi
        options+=("$logs" "$status" "$verify")
        if wizard_python run_menu.py has-reviews "$run"; then options+=("$reviews" "$follow"); fi
        options+=("$export")
        if wizard_python run_menu.py batch "$run"; then options+=("$watch"); fi
        options+=("$template")
        choice="$(wizard_select "${summary}"$'\n\n'"この run で何をしますか？" "${options[@]}")" || rc=$?
        [ "$rc" -eq 0 ] || { [ "$rc" -eq 10 ] && return 0; return "$rc"; }
        case "$choice" in
            "$logs") wizard_run_logs "$run" || rc=$? ;;
            "$status")
                if [ -s "$run/live/status.json" ]; then wizard_exec 'status.json' python3 -m json.tool "$run/live/status.json" || rc=$?
                else wizard_banner 'status.json はまだ空です（実行中か、準備だけの run です）。' || rc=$?; fi ;;
            "$verify") wizard_exec '成果物の点検' wizard_cli verify-run "$run" || rc=$? ;;
            "$reviews") wizard_exec '相互監査' wizard_cli reviews "$run" || rc=$? ;;
            "$follow") wizard_exec '相互監査（追いかけ表示）' wizard_cli reviews "$run" --follow || rc=$? ;;
            "$export") wizard_exec '会話履歴の保存' wizard_cli history "$run" || rc=$? ;;
            "$watch") wizard_exec '会話履歴の回収（ジョブの終了まで待ちます。Ctrl+C で戻る）' wizard_cli history --watch "$run" || rc=$? ;;
            "$template") wizard_run_template "$run" || rc=$? ;;
            "$resume") wizard_exec '会話の再開' wizard_cli resume "$run" || rc=$? ;;
        esac
        wizard_menu_rc "$rc" || return $?
    done
}

wizard_run_logs() {
    local run="$1" name size choice rc=0 how
    local -a files=() labels=()
    while IFS=$'\t' read -r name size; do
        [ -n "$name" ] || continue
        files+=("$name") labels+=("$name（$size）")
    done < <(wizard_python run_menu.py logs "$run" 2>/dev/null)
    if [ "${#files[@]}" -eq 0 ]; then
        wizard_banner 'まだ中身のあるログはありません。' || return $?
        return 0
    fi
    while :; do
        rc=0
        choice="$(wizard_select 'どのログを見ますか？' "${labels[@]}")" || rc=$?
        [ "$rc" -eq 0 ] || { [ "$rc" -eq 10 ] && return 0; return "$rc"; }
        name="${choice%%（*}"
        how="$(wizard_select "$name をどう表示しますか？" '末尾 200 行を表示する' '追いかけて表示する（新しい行を待つ。Ctrl+C で戻る）')" || rc=$?
        [ "$rc" -ne 10 ] || continue
        [ "$rc" -eq 0 ] || return "$rc"
        case "$how" in
            末尾*) wizard_exec "$name（末尾 200 行）" tail -n 200 "$run/live/$name" || rc=$? ;;
            *) wizard_exec "$name（追いかけ表示）" tail -n 50 -f "$run/live/$name" || rc=$? ;;
        esac
        wizard_menu_rc "$rc" || return $?
    done
}

wizard_run_template() {
    local run="$1" rc=0 out
    wizard_template_name '' || rc=$?
    [ "$rc" -eq 0 ] || return "$rc"
    out="$(template_tool from-run "$WIZARD_NAME" --run "$PWD/.agent-runs" "${WIZARD_FORCE[@]+"${WIZARD_FORCE[@]}"}" -- "$run" 2>&1)" || true
    WIZARD_TEMPLATE_CACHE=''
    wizard_banner "$out"
}

# ---------------------------------------------------------------------------
# Conversation history
# ---------------------------------------------------------------------------

wizard_history_schedule() {
    local state choice rc=0 directory at
    local add='登録する（登録済みなら置き換える）' off='解除する'
    state="$(wizard_python history_schedule.py show 2>&1)" || state="（状態を読めません）"
    choice="$(wizard_select "${state}"$'\n\n'"毎日決まった時刻に、実行中のセッションも含めて全部の会話を書き出します。" "$add" "$off")" || rc=$?
    [ "$rc" -eq 0 ] || { [ "$rc" -eq 10 ] && return 0; return "$rc"; }
    if [ "$choice" = "$off" ]; then
        wizard_exec '自動書き出しの解除' wizard_python history_schedule.py remove
        return
    fi
    directory="$(cat "$WIZARD_EXPORT_DIR_FILE" 2>/dev/null || true)"
    directory="$(wizard_path_input '書き出し先のフォルダ（Obsidian の保管庫の中のフォルダなど）' "${directory:-$HOME/agent-history}")" || return $?
    directory="$(wizard_expand_tilde "$directory")"
    [ -n "$directory" ] || { wizard_banner 'フォルダを入力してください。'; return; }
    at="$(wizard_input '毎日の実行時刻（東京時間、時:分）' '04:00')" || return $?
    mkdir -p "$(dirname "$WIZARD_EXPORT_DIR_FILE")" && printf '%s\n' "$directory" > "$WIZARD_EXPORT_DIR_FILE"
    wizard_exec '自動書き出しの登録' wizard_python history_schedule.py install "$directory" --at "${at:-04:00}"
}

wizard_history() {
    local list='一覧を見る（新しい順）' search='キーワードで検索する' export='Markdown として書き出す（Obsidian など向け）'
    local rename='会話の名前を変える' schedule='毎日の自動書き出しを設定する（cron）'
    local choice rc filter words directory
    while :; do
        rc=0
        choice="$(wizard_select '会話履歴 — 保存した全プロジェクトの会話が対象です' "$list" "$search" "$rename" "$export" "$schedule")" || rc=$?
        [ "$rc" -eq 0 ] || { [ "$rc" -eq 10 ] && return 0; return "$rc"; }
        case "$choice" in
            "$list")
                filter="$(wizard_input '作業リポジトリのパスの一部で絞り込む（空ならすべて）' '')" || rc=$?
                [ "$rc" -ne 10 ] || continue
                [ "$rc" -eq 0 ] || return "$rc"
                wizard_exec '会話履歴の一覧' wizard_python history_index.py list --limit 30 ${filter:+--repo "$filter"} || rc=$? ;;
            "$search")
                words="$(wizard_input '検索する語（空白で区切ると、すべてを含む会話）' '')" || rc=$?
                [ "$rc" -ne 10 ] || continue
                [ "$rc" -eq 0 ] || return "$rc"
                local -a terms=()
                read -r -a terms <<< "$words"
                if [ "${#terms[@]}" -eq 0 ]; then wizard_banner '検索する語を入力してください。' || rc=$?
                else wizard_exec "会話履歴の検索: $words" wizard_python history_index.py search "${terms[@]}" --limit 30 || rc=$?; fi ;;
            "$rename") wizard_history_rename || rc=$? ;;
            "$schedule") wizard_history_schedule || rc=$? ;;
            "$export")
                directory="$(cat "$WIZARD_EXPORT_DIR_FILE" 2>/dev/null || true)"
                directory="$(wizard_path_input '書き出し先のフォルダ（Obsidian の保管庫の中のフォルダなど）' "${directory:-$HOME/agent-history}")" || rc=$?
                [ "$rc" -ne 10 ] || continue
                [ "$rc" -eq 0 ] || return "$rc"
                directory="$(wizard_expand_tilde "$directory")"
                [ -n "$directory" ] || { wizard_banner 'フォルダを入力してください。' || return $?; continue; }
                if wizard_confirm "$directory に、1 会話 1 ファイルで書き出します。2 回目以降は変わった会話だけ書き直し、このコマンドが書いていないファイルには触れません。書き出しますか？" 1; then
                    mkdir -p "$(dirname "$WIZARD_EXPORT_DIR_FILE")" && printf '%s\n' "$directory" > "$WIZARD_EXPORT_DIR_FILE"
                    local live=()
                    if wizard_confirm '実行中のセッションも、今の時点の内容で保存してから書き出しますか？（終了時の保存で、あとから全文に置き換わります）' 1; then live=(--live)
                    else rc=$?; [ "$rc" -ne 10 ] || continue; [ "$rc" -eq 1 ] || return "$rc"; rc=0; fi
                    wizard_exec '会話履歴の書き出し' wizard_python history_index.py export-md "$directory" "${live[@]+"${live[@]}"}" || rc=$?
                else rc=$?; fi ;;
        esac
        wizard_menu_rc "$rc" || return $?
    done
}

wizard_history_rename() {
    local id label current choice name rc=0 index
    local -a ids=() labels=() names=()
    while IFS=$'\t' read -r id label current; do
        [ -n "$id" ] || continue
        ids+=("$id") labels+=("$label") names+=("$current")
    done < <(wizard_python history_index.py choices --limit 40 2>/dev/null)
    if [ "${#ids[@]}" -eq 0 ]; then
        wizard_banner '保存された会話はまだありません。'
        return $?
    fi
    choice="$(wizard_select '名前を変える会話を選んでください（新しい順に 40 件）' "${labels[@]}")" || rc=$?
    [ "$rc" -eq 0 ] || { [ "$rc" -eq 10 ] && return 0; return "$rc"; }
    for index in "${!labels[@]}"; do
        [ "${labels[$index]}" != "$choice" ] || { id="${ids[$index]}"; current="${names[$index]}"; }
    done
    name="$(wizard_input '新しい名前（空にすると、エージェントが付けた名前に戻します）' "$current")" || rc=$?
    [ "$rc" -ne 10 ] || return 0
    [ "$rc" -eq 0 ] || return "$rc"
    if [ -n "$name" ]; then
        wizard_exec '会話の名前の変更' wizard_python history_index.py rename "$id" "$name"
    elif wizard_confirm '名前が空です。自分で付けた名前を消して、エージェントが付けた名前に戻しますか？' 0; then
        wizard_exec '会話の名前を元に戻す' wizard_python history_index.py rename "$id" --clear
    else
        rc=$?
        [ "$rc" -eq 1 ] || return "$rc"
    fi
}

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

wizard_auth_agent() {
    # Sets WIZARD_AUTH_ARGS for the chosen agent.
    local prompt="$1" all_label="$2" choice
    local claude='claude（Claude Code）' codex='codex（Codex）' agy='antigravity（Antigravity CLI）'
    choice="$(wizard_select "$prompt" "$claude" "$codex" "$agy" ${all_label:+"$all_label"})" || return $?
    case "$choice" in
        "$claude") WIZARD_AUTH_ARGS=(--agent claude) ;;
        "$codex") WIZARD_AUTH_ARGS=(--agent codex) ;;
        "$agy") WIZARD_AUTH_ARGS=(--agent antigravity) ;;
        *) WIZARD_AUTH_ARGS=(--all) ;;
    esac
}

wizard_auth() {
    local status='状態を確認する' login='ログインする（各 CLI のログインを起動します）'
    local import='ホストでログイン済みの認証を取り込む' reset='保存した認証を削除する（リセット）'
    local choice rc
    local -a WIZARD_AUTH_ARGS=()
    while :; do
        rc=0
        choice="$(wizard_select '認証 — 取り込んだ認証は、実行中の run にも反映されます' "$status" "$login" "$import" "$reset")" || rc=$?
        [ "$rc" -eq 0 ] || { [ "$rc" -eq 10 ] && return 0; return "$rc"; }
        case "$choice" in
            "$status") wizard_exec '認証の状態' wizard_cli auth status || rc=$? ;;
            "$login")
                wizard_auth_agent 'どのエージェントにログインしますか？' 'すべて（claude・codex・antigravity）' || rc=$?
                [ "$rc" -ne 0 ] || wizard_exec 'ログイン' wizard_cli auth login "${WIZARD_AUTH_ARGS[@]}" || rc=$? ;;
            "$import")
                wizard_auth_agent 'どのエージェントの認証を取り込みますか？' 'すべて（claude・codex・antigravity）' || rc=$?
                [ "$rc" -ne 0 ] || wizard_exec '認証の取り込み' wizard_cli auth import "${WIZARD_AUTH_ARGS[@]}" || rc=$? ;;
            "$reset")
                wizard_auth_agent 'どのエージェントの保存済み認証を削除しますか？' '' || rc=$?
                if [ "$rc" -eq 0 ]; then
                    if wizard_confirm "${WIZARD_AUTH_ARGS[1]} の保存済み認証を削除します。次に使う前にログインか取り込みが必要になります。削除しますか？" 0; then
                        wizard_exec '認証の削除' wizard_cli auth reset "${WIZARD_AUTH_ARGS[@]}" || rc=$?
                    else rc=$?; fi
                fi ;;
        esac
        wizard_menu_rc "$rc" || return $?
    done
}

# ---------------------------------------------------------------------------
# Environment checks and maintenance
# ---------------------------------------------------------------------------

wizard_checks() {
    local doctor='起動に必要なものを点検する（doctor）' agents='エージェント CLI があるか確認する（agents）'
    local validate='このリポジトリの設定ファイルを検証する（validate）'
    local smoke='Slurm で最小のテストジョブを動かす（smoke-test）'
    local sync='フックとスキルの設定を同期し直す（sync-claude / sync-codex / sync-antigravity）'
    local choice rc which
    while :; do
        rc=0
        choice="$(wizard_select '環境の点検と設定' "$doctor" "$agents" "$validate" "$smoke" "$sync")" || rc=$?
        [ "$rc" -eq 0 ] || { [ "$rc" -eq 10 ] && return 0; return "$rc"; }
        case "$choice" in
            "$doctor")
                which="$(wizard_select 'どのエージェントについて点検しますか？' claude codex antigravity 'すべて')" || rc=$?
                if [ "$rc" -eq 0 ]; then
                    case "$which" in すべて) wizard_exec 'doctor' wizard_cli doctor --all || rc=$? ;;
                        *) wizard_exec "doctor（$which）" wizard_cli doctor --agent "$which" || rc=$? ;; esac
                fi ;;
            "$agents") wizard_exec 'エージェント CLI' wizard_cli agents || rc=$? ;;
            "$validate") wizard_exec 'validate' wizard_cli validate || rc=$? ;;
            "$smoke")
                which="$(wizard_select 'どのエージェントで試しますか？' claude codex antigravity)" || rc=$?
                if [ "$rc" -eq 0 ]; then
                    if wizard_confirm 'sbatch で投入しますか？（No なら投入用ファイルを作るだけ）' 1; then
                        wizard_exec "smoke-test（$which）" wizard_cli smoke-test --agent "$which" --submit || rc=$?
                    else
                        rc=$?
                        [ "$rc" -ne 1 ] || { rc=0; wizard_exec "smoke-test（$which、準備のみ）" wizard_cli smoke-test --agent "$which" || rc=$?; }
                    fi
                fi ;;
            "$sync")
                which="$(wizard_select 'どれを同期しますか？（agentrun リポジトリ内の設定ファイルを書き換えます）' \
                    'Claude Code（agents/claude/settings.json のフック、CLAUDE.md、skills）' \
                    'Codex（agents/codex/requirements.toml のフック、AGENTS.md、skills）' \
                    'Antigravity（agents/antigravity/hooks.json のフック、GEMINI.md、skills）')" || rc=$?
                if [ "$rc" -eq 0 ]; then
                    case "$which" in Claude*) wizard_exec 'sync-claude' wizard_cli sync-claude || rc=$? ;;
                        Codex*) wizard_exec 'sync-codex' wizard_cli sync-codex || rc=$? ;;
                        *) wizard_exec 'sync-antigravity' wizard_cli sync-antigravity || rc=$? ;; esac
                fi ;;
        esac
        wizard_menu_rc "$rc" || return $?
    done
}

# ---------------------------------------------------------------------------
# Skills and goal files
# ---------------------------------------------------------------------------

wizard_extend() {
    local skill='スキルを追加する（フォルダか Git の URL から）' goal='目標ファイル goal.yaml の雛形を作る'
    local choice rc source names
    while :; do
        rc=0
        choice="$(wizard_select 'スキルの追加と目標ファイル' "$skill" "$goal")" || rc=$?
        [ "$rc" -eq 0 ] || { [ "$rc" -eq 10 ] && return 0; return "$rc"; }
        case "$choice" in
            "$skill")
                source="$(wizard_input 'スキルのあるフォルダのパス、または Git の URL' '')" || rc=$?
                [ "$rc" -ne 10 ] || continue
                [ "$rc" -eq 0 ] || return "$rc"
                source="$(wizard_expand_tilde "$source")"
                [ -n "$source" ] || { wizard_banner 'パスか URL を入力してください。' || return $?; continue; }
                names="$(wizard_input '入れるスキルの名前（空白区切り。空ならすべて）' '')" || rc=$?
                [ "$rc" -ne 10 ] || continue
                [ "$rc" -eq 0 ] || return "$rc"
                local -a wanted=() force=()
                read -r -a wanted <<< "$names"
                if wizard_confirm '同じ名前のスキルが既にあれば上書きしますか？' 0; then force=(--force)
                else rc=$?; [ "$rc" -eq 1 ] || return "$rc"; rc=0; fi
                wizard_exec 'スキルの追加' wizard_cli skill-install "$source" "${wanted[@]+"${wanted[@]}"}" "${force[@]+"${force[@]}"}" || rc=$? ;;
            "$goal")
                if [ -e "$PWD/goal.yaml" ]; then
                    wizard_banner "$PWD/goal.yaml は既にあります。そのまま編集して、起動時の目標ファイルに指定してください。" || rc=$?
                elif wizard_confirm "$PWD/goal.yaml を雛形から作ります。作りますか？" 1; then
                    wizard_exec 'goal.yaml の作成' wizard_cli init-goal || rc=$?
                else rc=$?; fi ;;
        esac
        wizard_menu_rc "$rc" || return $?
    done
}
