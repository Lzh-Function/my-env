# wizard の UI・ナビゲーション・前回値（agentrun から source する）。
# UI の終了コード: 0=回答、1=No、10=戻る、130=キャンセル。
WIZARD_BACK='← 戻る'
WIZARD_CANCEL='キャンセル'
WIZARD_LAST_FILE="$HOME/.agentrun/wizard-last"
WIZARD_NO_OVERLAP='新しい Slurm ジョブを起動する（overlap しない）'
WIZARD_NO_TEMPLATE='テンプレートを使わない'
WIZARD_MANAGE_TEMPLATES='テンプレートを管理する（run から登録・削除・一覧）'
WIZARD_TEMPLATE_KEEP=0 WIZARD_NAME='' WIZARD_FORCE=() WIZARD_TEMPLATE_CACHE=''
declare -A WIZARD_LAST=() WIZARD_EXPLICIT=()
WIZARD_LAST_BINDS=() WIZARD_OVERLAP_JOBS=()
WIZARD_OVERLAP_LOADED=0 WIZARD_OVERLAP_INFO=''

wizard_abort() {
    trap - INT TERM
    printf '\nwizard をキャンセルしました。何も起動していません\n' >&2
    exit 130
}

wizard_navigation() {
    case "$1" in
        "$WIZARD_BACK"|:back) return 10 ;;
        "$WIZARD_CANCEL"|:cancel|$'\e') return 130 ;;
    esac
}

wizard_readline_keys() {
    # read -e は各 UI の子 shell で使うため、親端末の設定には残らない。
    bind '"\e": "\C-u:cancel\C-m"' 2>/dev/null || true
    bind '"\C-g": "\C-u:cancel\C-m"' 2>/dev/null || true
    bind '"\e[1;3D": "\C-u:back\C-m"' 2>/dev/null || true
}

wizard_banner() {
    case "$WIZARD_UI" in
        gum) gum style --border rounded --margin '1 0' --padding '0 2' --border-foreground 212 "$1" ;;
        whiptail|dialog) "$DIALOG_BIN" --title 'agentrun wizard' --msgbox "$1" 20 90 || return 130 ;;
        *) printf '\n\033[1;35m== %s ==\033[0m\n' "$1" >&2 ;;
    esac
}

wizard_select() {
    local prompt="$1" choice="" rc=0; shift
    local -a opts=("$@" "$WIZARD_BACK" "$WIZARD_CANCEL")
    case "$WIZARD_UI" in
        gum) choice="$(gum choose --header "$prompt" "${opts[@]}")" || return 130 ;;
        whiptail|dialog)
            local -a menu_args=()
            local opt
            for opt in "${opts[@]}"; do menu_args+=("$opt" ""); done
            # Size the box to a multi-line heading (e.g. a run summary) and the options, within the screen.
            local lines height lists
            lines="$(printf '%s\n' "$prompt" | wc -l)"
            lists="${#opts[@]}"
            height=$((lines + lists + 7))
            [ "$height" -le "$(( ${LINES:-$(tput lines 2>/dev/null || echo 24)} - 1 ))" ] || height=$(( ${LINES:-$(tput lines 2>/dev/null || echo 24)} - 1 ))
            [ "$height" -ge 12 ] || height=12
            [ "$lists" -le $((height - lines - 7)) ] || lists=$((height - lines - 7))
            [ "$lists" -ge 3 ] || lists=3
            choice="$("$DIALOG_BIN" --title 'agentrun wizard' --menu "$prompt" "$height" 90 "$lists" "${menu_args[@]}" 3>&1 1>&2 2>&3)" || return 130
            ;;
        *)
            printf '\033[1;36m%s\033[0m\n' "$prompt" >&2
            wizard_readline_keys
            local n
            for n in "${!opts[@]}"; do printf '%d) %s\n' "$((n + 1))" "${opts[n]}" >&2; done
            while :; do
                read -e -r -p '番号を入力 (Enter=1, :back=戻る, :cancel=キャンセル) ' choice || return 130
                [ -n "$choice" ] || choice=1
                wizard_navigation "$choice" || return $?
                if [[ "$choice" =~ ^[0-9]+$ ]] && [ "${#choice}" -lt 5 ] && [ "$((10#$choice))" -ge 1 ] && [ "$((10#$choice))" -le "${#opts[@]}" ]; then
                    choice="${opts[$((10#$choice - 1))]}"
                    break
                fi
                for opt in "${opts[@]}"; do [ "$choice" != "$opt" ] || break 2; done
            done
            ;;
    esac
    wizard_navigation "$choice" || return $?
    printf '%s\n' "$choice"
}

wizard_input() {
    local prompt="$1" default="${2:-}" value
    prompt+=" (:back=戻る, :cancel=キャンセル)"
    case "$WIZARD_UI" in
        gum) value="$(gum input --char-limit 0 --header "$prompt" --value "$default")" || return 130 ;;
        whiptail|dialog)
            value="$("$DIALOG_BIN" --title 'agentrun wizard' --inputbox "$prompt" 12 90 "$default" 3>&1 1>&2 2>&3)" || return 130 ;;
        *)
            printf '\033[1;36m%s\033[0m\n' "$prompt" >&2
            wizard_readline_keys
            read -e -r -i "$default" -p '> ' value || return 130
            ;;
    esac
    wizard_navigation "$value" || return $?
    printf '%s\n' "$value"
}

wizard_path_input() {
    local value default="${2:-}"
    [ -z "$default" ] || default="$(wizard_shell_quote "$default")"
    printf '\033[1;36m%s\033[0m\n' "$1" >&2
    printf '\033[1;36mTab=パス補完 / :back=戻る (Alt+←) / :cancel=キャンセル (Ctrl+G・Esc)\033[0m\n' >&2
    wizard_readline_keys
    IFS= read -e -r -i "$default" -p '> ' value || return 130
    wizard_navigation "$value" || return $?
    python3 "$ROOT_DIR/runtime/agentrun/path-input.py" "$value"
}

wizard_confirm() {
    local prompt="$1" default_yes="${2:-0}" choice rc=0
    if [ "$WIZARD_UI" = plain ]; then
        local suffix='[y/N]'
        [ "$default_yes" -eq 0 ] || suffix='[Y/n]'
        wizard_readline_keys
        # A long or multi-line prompt inside read -p is cut by Readline, so print it first.
        printf '\033[1;36m%s\033[0m\n' "$prompt" >&2
        read -e -r -p "$suffix (:back=戻る, :cancel=キャンセル): " choice || return 130
        wizard_navigation "$choice" || return $?
        if [ -z "$choice" ]; then [ "$default_yes" -eq 1 ]; return; fi
        case "$choice" in y|Y|yes|Yes|YES) return 0 ;; *) return 1 ;; esac
    fi
    local -a opts=(はい いいえ)
    [ "$default_yes" -eq 1 ] || opts=(いいえ はい)
    choice="$(wizard_select "$prompt" "${opts[@]}")" || return $?
    [ "$choice" = はい ]
}

wizard_ask() {
    local var="$1" prompt="$2" value="$3" validator="${4:-}" out rc
    while :; do
        case "$validator" in
            wizard_valid_repo|wizard_valid_goal|wizard_valid_path) value="$(wizard_path_input "$prompt" "$value")" || return $? ;;
            *) value="$(wizard_input "$prompt" "$value")" || return $? ;;
        esac
        if [ -z "$validator" ]; then printf -v "$var" '%s' "$value"; return; fi
        if out="$("$validator" "$value")"; then printf -v "$var" '%s' "$out"; return; fi
        wizard_banner "$out" || return $?
    done
}

wizard_expand_tilde() {
    case "$1" in '~') printf '%s\n' "$HOME" ;; '~/'*) printf '%s/%s\n' "$HOME" "${1:2}" ;; *) printf '%s\n' "$1" ;; esac
}

wizard_mode_label() {
    case "$1" in
        assist) printf 'assist（対話で作業する。バッチ投入もできます）' ;;
        experiment) printf 'experiment（目標に沿って実験し、次の作業を提案する）' ;;
        campaign) printf 'campaign（長時間の継続実験。学習ジョブの提案も書く）' ;;
        resume) printf 'resume（保存した会話を再開する）' ;;
        *) printf '%s' "$1" ;;
    esac
}

wizard_valid_repo() {
    local path
    path="$(wizard_expand_tilde "${1:-.}")"
    [ -d "$path" ] || { printf '作業リポジトリのパスがディレクトリではありません: %s\n' "$1"; return 1; }
    path="$(readlink -f "$path")"
    if [ -n "${OVERLAP_JOB:-}" ] && repo_lock_busy "$path"; then
        printf '%s では既に agentrun が動いています。overlap するときは、別のリポジトリか git worktree を選んでください\n' "$path"
        return 1
    fi
    printf '%s\n' "$path"
}

wizard_valid_gpus() {
    [[ "$1" =~ ^[0-9]+$ ]] && [ "${#1}" -lt 9 ] || { printf 'GPU 数は 0 以上の整数で入力してください\n'; return 1; }
    printf '%s\n' "$((10#$1))"
}

wizard_valid_mem() {
    [[ "$1" =~ ^[1-9][0-9]*[KMGTkmgt]?$ ]] || { printf 'メモリは 16000M や 64G の形で入力してください: %s\n' "$1"; return 1; }
    printf '%s\n' "$1"
}

wizard_valid_cpus() {
    [[ "$1" =~ ^[0-9]+$ ]] && [ "${#1}" -lt 9 ] && [ "$((10#$1))" -gt 0 ] || { printf 'CPU コア数は 1 以上の整数で入力してください: %s\n' "$1"; return 1; }
    printf '%s\n' "$((10#$1))"
}

wizard_valid_time() {
    [[ "$1" =~ ^([0-9]+-)?[0-9]+(:[0-5][0-9]){0,2}$ ]] || { printf '制限時間は HH:MM:SS、MM、D-HH:MM:SS のいずれかの形で入力してください: %s\n' "$1"; return 1; }
    printf '%s\n' "$1"
}

wizard_valid_goal() {
    [ -n "$1" ] || { printf '\n'; return; }
    local path
    path="$(wizard_expand_tilde "$1")"
    [ -f "$path" ] || { printf '目標ファイルがありません: %s\n' "$1"; return 1; }
    readlink -f "$path"
}

wizard_valid_path() {
    wizard_expand_tilde "$1"
}

wizard_valid_prompt() {
    [ -n "${1//[[:space:]]/}" ] || { printf '作業の指示（プロンプト）を入力してください\n'; return 1; }
    printf '%s\n' "$1"
}

wizard_shell_quote() {
    if [[ "$1" =~ ^[A-Za-z0-9_./:=@%+,-]+$ ]]; then printf '%s' "$1"
    else printf "'%s'" "${1//\'/\'\\\'\'}"; fi
}

wizard_load_last() {
    WIZARD_LAST=() WIZARD_LAST_BINDS=()
    local key value
    while IFS= read -r -d '' key && IFS= read -r -d '' value; do
        if [ "$key" = bind ]; then WIZARD_LAST_BINDS+=("$value")
        else WIZARD_LAST["$key"]="$value"; fi
    done < <(python3 "$ROOT_DIR/runtime/agentrun/wizard-state.py" load "$WIZARD_LAST_FILE")
}

wizard_save_last() {
    local mode="$1" profile="$2" bind
    local -a state=(cwd "$PWD" mode "$mode" profile "$profile" agent "$AGENT" repo "$REPO" submit "$SUBMIT"
        mem "$MEM" cpus "$CPUS" time "$TIME_LIMIT" gh_broker "$((1 - GH_BROKER_DISABLED))"
        goal "$GOAL" prompt "$PROMPT"
        partition "$PARTITION" gpus "$GPUS" allow_fuse "$ALLOW_FUSE" secrets "$(secrets_enabled && printf 1 || printf 0)"
        resume_id "${selected%% *}")
    for bind in "${EXTRA_BINDS[@]+"${EXTRA_BINDS[@]}"}"; do state+=(bind "$bind"); done
    python3 "$ROOT_DIR/runtime/agentrun/wizard-state.py" save "$WIZARD_LAST_FILE" "${state[@]}"
}

wizard_resource_default() {
    local key="$1" profile="$2" current="$3"
    if [ -z "$current" ] && [ -z "${WIZARD_EXPLICIT[$key]:-}" ] && [ "${WIZARD_LAST[profile]:-${WIZARD_LAST[mode]:-}}" = "$profile" ]; then
        current="${WIZARD_LAST[$key]:-$current}"
    fi
    if [ -n "$current" ]; then printf '%s\n' "$current"
    else "profile_$key" "$profile"; fi
}

# Only interactive launches can join an existing allocation. Query Slurm once,
# and only when such a launch is selected.
wizard_overlap_available() {
    [ "$mode" = resume ] || { [ "$mode" = assist ] && [ "$SUBMIT" -eq 0 ]; } || return 1
    if [ "$WIZARD_OVERLAP_LOADED" -eq 0 ]; then
        WIZARD_OVERLAP_LOADED=1
        local jobs
        jobs="$(overlap_tool jobs "$PWD/.agent-runs")" || jobs=''
        [ -z "$jobs" ] || mapfile -t WIZARD_OVERLAP_JOBS <<< "$jobs"
    fi
    [ "${#WIZARD_OVERLAP_JOBS[@]}" -gt 0 ] || [ -n "$OVERLAP_JOB" ]
}

wizard_overlap() {
    local -a options=() info
    local line choice fields prompt
    # Keep a previously chosen job first; otherwise default to a new job.
    if [ -n "$OVERLAP_JOB" ]; then
        for line in "${WIZARD_OVERLAP_JOBS[@]+"${WIZARD_OVERLAP_JOBS[@]}"}"; do
            [ "${line%% *}" != "$OVERLAP_JOB" ] || options+=("$line")
        done
        [ "${#options[@]}" -gt 0 ] || options+=("$OVERLAP_JOB  （指定したジョブ）")
    fi
    options+=("$WIZARD_NO_OVERLAP")
    for line in "${WIZARD_OVERLAP_JOBS[@]+"${WIZARD_OVERLAP_JOBS[@]}"}"; do
        [ "${line%% *}" = "$OVERLAP_JOB" ] || options+=("$line")
    done
    if [ "${#options[@]}" -eq 2 ]; then
        prompt='実行中の Slurm ジョブがあります。このジョブに overlap して、同じ割り当て内でエージェントコンテナをもう一つ起動しますか？'
    else
        prompt="実行中の Slurm ジョブが $((${#options[@]} - 1)) 件あります。どれかに overlap して、同じ割り当て内でエージェントコンテナをもう一つ起動しますか？"
    fi
    while :; do
        choice="$(wizard_select "$prompt" "${options[@]}")" || return $?
        if [ "$choice" = "$WIZARD_NO_OVERLAP" ]; then
            OVERLAP_JOB='' WIZARD_OVERLAP_INFO=''
            return 0
        fi
        if fields="$(overlap_tool info "${choice%% *}" 2>&1)"; then
            mapfile -t info <<< "$fields"
            OVERLAP_JOB="${info[0]}"
            WIZARD_OVERLAP_INFO="job ${info[0]}${info[7]:+（${info[7]}）} / ノード: ${info[4]} / パーティション: ${info[3]} / CPU: ${info[1]} / GPU: ${info[2]} / 制限時間: ${info[5]}（経過 ${info[6]}）"
            return 0
        fi
        wizard_banner "$fields" || return $?
    done
}

# Decided once per mode, so saving a template mid-way never shifts the step list.
wizard_templates_available() {
    if [ "${WIZARD_TEMPLATE_CACHE%%=*}" != "$mode" ]; then
        WIZARD_TEMPLATE_CACHE="$mode=0"
        [ -z "$(template_tool list --mode "$mode" 2>/dev/null)" ] || WIZARD_TEMPLATE_CACHE="$mode=1"
    fi
    [ "${WIZARD_TEMPLATE_CACHE#*=}" = 1 ]
}

# Ask for a template name; sets WIZARD_NAME and WIZARD_FORCE (overwrite confirmed).
wizard_template_name() {
    local default="$1" rc
    while :; do
        WIZARD_NAME="$(wizard_input 'テンプレート名（英数字と . _ -、64文字まで）' "$default")" || return $?
        rc=0
        template_tool exists "$WIZARD_NAME" 2>/dev/null || rc=$?
        case "$rc" in
            1) WIZARD_FORCE=(); return 0 ;;
            0)
                if wizard_confirm "テンプレート「$WIZARD_NAME」は既にあります。上書きしますか？" 0; then WIZARD_FORCE=(--force); return 0
                else rc=$?; [ "$rc" -eq 1 ] || return "$rc"; fi ;;
            *) wizard_banner "テンプレート名には英数字と . _ - だけを使えます（先頭は英数字）: $WIZARD_NAME" || return $? ;;
        esac
        default="$WIZARD_NAME"
    done
}

wizard_template_manage() {
    local add='実行中・過去の run から登録する' remove='テンプレートを削除する' show='テンプレートの一覧と中身を見る'
    local choice row out rc
    local -a rows
    while :; do
        choice="$(wizard_select 'テンプレートの管理' "$add" "$remove" "$show")" || return $?
        rc=0
        case "$choice" in
            "$add")
                mapfile -t rows < <(template_tool runs "$PWD/.agent-runs" 2>/dev/null)
                if [ "${#rows[@]}" -eq 0 ]; then wizard_banner 'テンプレートにできる run がありません（このディレクトリの .agent-runs）' || return $?; continue; fi
                row="$(wizard_select 'テンプレートにする run（実行中のものが先頭）' "${rows[@]}")" || rc=$?
                [ "$rc" -ne 10 ] || continue
                [ "$rc" -eq 0 ] || return "$rc"
                wizard_template_name '' || rc=$?
                [ "$rc" -ne 10 ] || continue
                [ "$rc" -eq 0 ] || return "$rc"
                out="$(template_tool from-run "$WIZARD_NAME" --run "$PWD/.agent-runs" "${WIZARD_FORCE[@]+"${WIZARD_FORCE[@]}"}" -- "${row%% *}" 2>&1)" || true
                wizard_banner "$out" || return $? ;;
            "$remove"|"$show")
                mapfile -t rows < <(template_tool list 2>/dev/null)
                if [ "${#rows[@]}" -eq 0 ]; then wizard_banner 'テンプレートはまだありません' || return $?; continue; fi
                row="$(wizard_select "$([ "$choice" = "$remove" ] && printf '削除するテンプレート' || printf '中身を見るテンプレート')" "${rows[@]}")" || rc=$?
                [ "$rc" -ne 10 ] || continue
                [ "$rc" -eq 0 ] || return "$rc"
                out="$(template_tool show "${row%% *}" 2>&1)" || true
                if [ "$choice" = "$show" ]; then wizard_banner "$out" || return $?; continue; fi
                if wizard_confirm "${out}"$'\n\n'"このテンプレートを削除しますか？" 0; then
                    out="$(template_tool delete "${row%% *}" 2>&1)" || true
                    wizard_banner "$out" || return $?
                else rc=$?; [ "$rc" -eq 1 ] || [ "$rc" -eq 10 ] || return "$rc"; fi ;;
        esac
    done
}

# Offer the templates saved for this mode; a chosen template replaces the current values.
wizard_template() {
    local -a rows options=()
    local row choice name detail prompt="$PROMPT" rc
    mapfile -t rows < <(template_tool list --mode "$mode" 2>/dev/null)
    for row in "${rows[@]+"${rows[@]}"}"; do [ "${row%% *}" != "$TEMPLATE_NAME" ] || options+=("$row"); done
    options+=("$WIZARD_NO_TEMPLATE")
    for row in "${rows[@]+"${rows[@]}"}"; do [ "${row%% *}" = "$TEMPLATE_NAME" ] || options+=("$row"); done
    while :; do
        choice="$(wizard_select 'テンプレートから始めますか？' "${options[@]}")" || return $?
        if [ "$choice" = "$WIZARD_NO_TEMPLATE" ]; then
            TEMPLATE_NAME='' WIZARD_TEMPLATE_KEEP=0
            return 0
        fi
        name="${choice%% *}"
        # Check in a subshell first: parse_run_args exits on an unusable value.
        if ! detail="$( (parse_run_args --template "$name") 2>&1 >/dev/null)"; then
            wizard_banner "テンプレート「$name」は使えません: $detail" || return $?
            continue
        fi
        parse_run_args --template "$name"
        PROMPT="$prompt"
        detail="$(template_tool show "$name")"
        rc=0
        if wizard_confirm "${detail}"$'\n\n'"このテンプレートの設定を変更しますか？" 0; then WIZARD_TEMPLATE_KEEP=0
        else
            rc=$?
            [ "$rc" -ne 10 ] || continue
            [ "$rc" -eq 1 ] || return "$rc"
            WIZARD_TEMPLATE_KEEP=1
        fi
        return 0
    done
}

wizard_template_save() {
    local skip='保存しない' new='新しい名前で保存する' choice rc=0 out
    if [ -n "$TEMPLATE_NAME" ]; then
        choice="$(wizard_select 'この設定をテンプレートとして保存しますか？（overlap 先と prompt は保存しません）' \
            "$skip" "テンプレート「$TEMPLATE_NAME」を上書きする" "$new")" || return $?
        case "$choice" in
            "$skip") return 0 ;;
            "$new") wizard_template_name '' || return $? ;;
            *) WIZARD_NAME="$TEMPLATE_NAME" WIZARD_FORCE=(--force) ;;
        esac
    else
        if wizard_confirm 'この設定をテンプレートとして保存しますか？（overlap 先と prompt は保存しません）' 0; then :
        else rc=$?; [ "$rc" -eq 1 ] && return 0; return "$rc"; fi
        wizard_template_name '' || return $?
    fi
    template_state_args || return $?
    out="$(template_tool save "$WIZARD_NAME" --mode "$mode" --agent "$AGENT" --submit "$SUBMIT" --source wizard \
        "${WIZARD_FORCE[@]+"${WIZARD_FORCE[@]}"}" -- "${TEMPLATE_STATE[@]}" 2>&1)" || true
    wizard_banner "$out"
}

wizard_bind_mounts() {
    local stage=0 rc src='' dst='' choice bind
    local keep='このまま次へ' add='bind を追加する' remove_one='bind を1つ除く（一覧から選択）' remove_all='bind を全て除く'
    while :; do
        rc=0
        case "$stage" in
            0)
                if [ "${#EXTRA_BINDS[@]}" -eq 0 ]; then
                    if wizard_confirm '追加の bind mount: なし。追加しますか？' 0; then stage=1
                    else rc=$?; [ "$rc" -ne 1 ] || return 0; return "$rc"; fi
                    continue
                fi
                choice="$(wizard_select "追加の bind mount: ${EXTRA_BINDS[*]}" "$keep" "$add" "$remove_one" "$remove_all")" || return $?
                case "$choice" in
                    "$keep") return 0 ;;
                    "$add") stage=1 ;;
                    "$remove_one") stage=3 ;;
                    "$remove_all") EXTRA_BINDS=() ;;
                esac ;;
            1)
                src="$(wizard_path_input 'bind mount の元（ホスト側のパス）' "$src")" || rc=$?
                [ "$rc" -ne 10 ] || { stage=0; continue; }
                [ "$rc" -eq 0 ] || return "$rc"
                src="$(wizard_expand_tilde "$src")"
                if [ -e "$src" ]; then src="$(readlink -f "$src")"; stage=2
                else wizard_banner "bind mount の元がありません: $src" || return $?; fi ;;
            2)
                dst="$(wizard_input 'コンテナ内のマウント先（例: /extra:ro。:ro で読み取り専用）' "$dst")" || rc=$?
                [ "$rc" -ne 10 ] || { stage=1; continue; }
                [ "$rc" -eq 0 ] || return "$rc"
                if [[ "$dst" =~ ^/[^:,]+(:(ro|rw))?$ ]]; then EXTRA_BINDS+=("$src:$dst"); stage=0; src=''; dst=''
                else wizard_banner 'マウント先は絶対パスで、末尾に :ro か :rw を付けられます' || return $?; fi ;;
            3)
                choice="$(wizard_select '除く bind mount を選んでください' "${EXTRA_BINDS[@]}")" || rc=$?
                [ "$rc" -ne 10 ] || { stage=0; continue; }
                [ "$rc" -eq 0 ] || return "$rc"
                local -a kept=()
                for bind in "${EXTRA_BINDS[@]}"; do
                    if [ -n "$choice" ] && [ "$bind" = "$choice" ]; then choice=''; else kept+=("$bind"); fi
                done
                EXTRA_BINDS=("${kept[@]+"${kept[@]}"}"); stage=0 ;;
        esac
    done
}

wizard_step() {
    local step="$1" choice rc=0 fields preview default key prompt
    case "$step" in
        mode)
            local -a modes=()
            default="${mode:-${TEMPLATE_MODE:-${WIZARD_LAST[mode]:-assist}}}"
            # dry-run only previews new launches, so resume is not offered there.
            [ "$WIZARD_DRY_RUN" -eq 0 ] || [ "$default" != resume ] || default=assist
            if is_profile "$default" || [ "$default" = resume ]; then modes+=("$default"); fi
            for choice in assist experiment campaign resume; do
                [ "$choice" != "$default" ] || continue
                [ "$WIZARD_DRY_RUN" -eq 0 ] || [ "$choice" != resume ] || continue
                modes+=("$choice")
            done
            prompt='実行モードを選んでください'
            [ "$WIZARD_DRY_RUN" -eq 0 ] || prompt+='（dry-run：起動せずに確認します）'
            local -a labels=()
            for choice in "${modes[@]}"; do labels+=("$(wizard_mode_label "$choice")"); done
            choice="$(wizard_select "$prompt" "${labels[@]}" "$WIZARD_MANAGE_TEMPLATES")" || return $?
            [ "$choice" = "$WIZARD_MANAGE_TEMPLATES" ] || choice="${choice%%（*}"
            if [ "$choice" = "$WIZARD_MANAGE_TEMPLATES" ]; then
                wizard_template_manage || rc=$?
                WIZARD_TEMPLATE_CACHE=''
                [ "$rc" -eq 0 ] || [ "$rc" -eq 10 ] || return "$rc"
                return 11
            fi
            if [ "$mode" != "$choice" ]; then
                MEM="$cli_mem"; CPUS="$cli_cpus"; TIME_LIMIT="$cli_time"; loaded_source=''
                [ "$choice" = "${TEMPLATE_MODE:-}" ] || TEMPLATE_NAME=''
                WIZARD_TEMPLATE_KEEP=0
            fi
            mode="$choice"
            ;;
        agent)
            local -a agents=("$AGENT")
            for choice in "${SUPPORTED_AGENTS[@]}"; do [ "$choice" = "$AGENT" ] || agents+=("$choice"); done
            choice="$(wizard_select 'エージェントを選んでください' "${agents[@]}")" || return $?
            AGENT="$choice" ;;
        session)
            local choices
            choices="$(session_tool choices "$PWD/.agent-runs")" || return $?
            local -a options values
            mapfile -t options <<< "$choices"
            default="${selected%% *}"
            if [ -n "$default" ]; then
                local -a ordered=()
                for choice in "${options[@]}"; do [ "${choice%% *}" != "$default" ] || ordered+=("$choice"); done
                for choice in "${options[@]}"; do [ "${choice%% *}" = "$default" ] || ordered+=("$choice"); done
                options=("${ordered[@]}")
            fi
            choice="$(wizard_select '再開する run を選択（run ID / agent / 最後の発言）' "${options[@]}")" || return $?
            source="$(session_tool resolve "$PWD/.agent-runs" "${choice%% *}")" || return $?
            fields="$(session_tool fields "$source")" || return $?
            mapfile -t values <<< "$fields"
            if [ "$source" != "$loaded_source" ]; then
                local fallback_mem="$MEM" fallback_cpus="$CPUS" fallback_time="$TIME_LIMIT" overlap_job="$OVERLAP_JOB"
                local -a fallback_binds=("${EXTRA_BINDS[@]+"${EXTRA_BINDS[@]}"}")
                load_resume_settings "$source" "${wizard_resume_overrides[@]}" || return $?
                # The overlap choice belongs to this launch, not to the saved run.
                OVERLAP_JOB="$overlap_job"
                # Pre-feature synthetic/old sessions may have no launch script at all.
                if [ ! -f "$source/launch.json" ] && [ ! -f "$source/submit.sbatch" ]; then
                    [ -n "$MEM" ] || MEM="$fallback_mem"
                    [ -n "$CPUS" ] || CPUS="$fallback_cpus"
                    [ -n "$TIME_LIMIT" ] || TIME_LIMIT="$fallback_time"
                    if [ "${#EXTRA_BINDS[@]}" -eq 0 ] && [ -z "${WIZARD_EXPLICIT[no-binds]:-}" ]; then
                        EXTRA_BINDS=("${fallback_binds[@]+"${fallback_binds[@]}"}")
                    fi
                fi
                loaded_source="$source"
            fi
            AGENT="${values[0]}" REPO="${values[1]}" profile="${values[2]}" selected="$choice"
            is_profile "$profile" || return 2 ;;
        preview)
            if wizard_confirm '直近の会話を表示しますか？' 0; then
                preview="$(session_tool preview "$source")" || return $?
                [ "${#preview}" -le 16000 ] || preview="（末尾16000文字。全文は resume RUN_ID --preview）"$'\n'"${preview: -16000}"
                wizard_banner "$preview" || return $?
            else rc=$?; [ "$rc" -eq 1 ] || return "$rc"; fi ;;
        launch)
            if [ "$mode" = assist ]; then
                local -a launches=('対話で起動する（srun --pty）' 'バッチで投入する（sbatch）')
                [ "$SUBMIT" -eq 0 ] || launches=('バッチで投入する（sbatch）' '対話で起動する（srun --pty）')
                choice="$(wizard_select '起動方法を選んでください' "${launches[@]}")" || return $?
                case "$choice" in 'バッチで投入する（sbatch）') SUBMIT=1 ;; *) SUBMIT=0 ;; esac
            else
                if wizard_confirm '今すぐ sbatch で投入しますか？（いいえ：起動に必要なファイルを準備するだけ）' "$SUBMIT"; then SUBMIT=1
                else rc=$?; [ "$rc" -eq 1 ] || return "$rc"; SUBMIT=0; fi
            fi ;;
        repo) wizard_ask REPO '作業リポジトリのパス（コンテナの /workspace になります）' "$REPO" wizard_valid_repo ;;
        mem) wizard_ask MEM 'メモリ（例: 16000M、64G）' "$(wizard_resource_default mem "$profile" "$MEM")" wizard_valid_mem ;;
        cpus) wizard_ask CPUS 'CPU コア数' "$(wizard_resource_default cpus "$profile" "$CPUS")" wizard_valid_cpus ;;
        time) wizard_ask TIME_LIMIT '制限時間（HH:MM:SS か D-HH:MM:SS）' "$(wizard_resource_default time "$profile" "$TIME_LIMIT")" wizard_valid_time ;;
        partition) wizard_ask PARTITION 'Slurm のパーティション（空ならクラスタの既定）' "$PARTITION" ;;
        gpus) wizard_ask GPUS 'GPU 数' "$GPUS" wizard_valid_gpus ;;
        fuse)
            if wizard_confirm '/dev/fuse をコンテナに渡しますか？（コンテナ内で apptainer や FUSE を使うとき）' "$ALLOW_FUSE"; then ALLOW_FUSE=1
            else rc=$?; [ "$rc" -eq 1 ] || return "$rc"; ALLOW_FUSE=0; fi ;;
        secrets)
            if wizard_confirm "$secrets_candidate の秘密情報を、環境変数としてコンテナに渡しますか？" "$(secrets_enabled && printf 1 || printf 0)"; then SECRETS_FILE="$secrets_candidate"
            else rc=$?; [ "$rc" -eq 1 ] || return "$rc"; SECRETS_FILE=''; fi ;;
        binds) wizard_bind_mounts ;;
        template) wizard_template ;;
        save) wizard_template_save ;;
        overlap) wizard_overlap ;;
        broker)
            if wizard_confirm 'GitHub 仲介（broker）を起動しますか？（トークンはコンテナの外に置いたまま push や gh を使えます）' "$((1 - GH_BROKER_DISABLED))"; then GH_BROKER_DISABLED=0
            else rc=$?; [ "$rc" -eq 1 ] || return "$rc"; GH_BROKER_DISABLED=1; fi
            resolve_gh_broker ;;
        goal) wizard_ask GOAL '目標ファイル goal.yaml のパス（任意。空なら使わない）' "$GOAL" wizard_valid_goal ;;
        prompt)
            if [ "$mode" = assist ] && [ "$SUBMIT" -eq 0 ]; then PROMPT=''
            else wizard_ask PROMPT '作業の指示（プロンプト）' "$PROMPT" wizard_valid_prompt; fi ;;
        confirm) wizard_finish ;;
    esac
}

wizard_finish() {
    local -a args
    if [ -n "$OVERLAP_JOB" ] && [ "$mode" != resume ] && repo_lock_busy "$(readlink -f "$REPO")"; then
        wizard_banner "$REPO では既に agentrun が動いています。overlap するときは、別のリポジトリか git worktree を選んでください" || return $?
        return 10
    fi
    if [ "$mode" = resume ]; then args=("$source" --no-binds)
    else args=(--agent "$AGENT" --repo "$REPO"); fi
    # An overlapping step uses the running job's resources.
    if [ -n "$OVERLAP_JOB" ]; then args+=(--overlap "$OVERLAP_JOB")
    else args+=(--mem "$MEM" --cpus "$CPUS" --time "$TIME_LIMIT" --partition "$PARTITION" --gpus "$GPUS"); fi
    local arg
    for arg in "${EXTRA_BINDS[@]+"${EXTRA_BINDS[@]}"}"; do args+=(--bind "$arg"); done
    if [ "$GH_BROKER_DISABLED" -eq 1 ]; then args+=(--no-gh-broker); else args+=(--gh-broker); fi
    if [ "$ALLOW_FUSE" -eq 1 ]; then args+=(--allow-fuse); else args+=(--no-allow-fuse); fi
    if secrets_enabled; then args+=(--secrets-file "$SECRETS_FILE"); else args+=(--no-secrets); fi
    [ -z "$GOAL" ] || args+=(--goal "$GOAL")
    if [ "$mode" != resume ]; then
        [ "$SUBMIT" -eq 0 ] || args+=(--submit)
        [ -z "$PROMPT" ] || args+=(-- "$PROMPT")
    fi
    local command_line="agentrun $mode" summary rc=0 key prefix=''
    for key in AGENT_REVIEW_CODEX_MODEL AGENT_REVIEW_CODEX_EFFORT AGENT_REVIEW_CLAUDE_MODEL AGENT_REVIEW_CLAUDE_EFFORT \
        AGENT_REVIEW_ANTIGRAVITY_MODEL AGENT_REVIEW_ANTIGRAVITY_EFFORT AGENT_REVIEW_ACTIVE_TIMEOUT; do
        [ -z "${!key:-}" ] || prefix+="$key=$(wizard_shell_quote "${!key}") "
    done
    [ -z "$prefix" ] || command_line="env $prefix$command_line"
    for arg in "${args[@]}"; do command_line+=" $(wizard_shell_quote "$arg")"; done
    summary="モード: $mode / エージェント: $AGENT / プロファイル: $profile"$'\n'"作業リポジトリ: $REPO"$'\n'
    [ -z "$TEMPLATE_NAME" ] || [ "$mode" = resume ] || summary+="テンプレート: $TEMPLATE_NAME$([ "$WIZARD_TEMPLATE_KEEP" -eq 1 ] && printf '（変更なし）' || printf '（変更あり）')"$'\n'
    if [ -n "$OVERLAP_JOB" ]; then
        summary+="overlap 先: ${WIZARD_OVERLAP_INFO:-job $OVERLAP_JOB}"$'\n'
        summary+="  CPU・メモリ・GPU・制限時間は元のジョブと共有し、元のジョブが終わるとこのコンテナも終了します"$'\n'
    else summary+="メモリ / CPU / 制限時間: $MEM / $CPUS / $TIME_LIMIT"$'\n'; fi
    [ "$mode" != resume ] || summary+="再開対象: $selected"$'\n'"$(settings_tool describe "$source")"$'\n'
    if [ -n "$OVERLAP_JOB" ]; then summary+="FUSE: $([ "$ALLOW_FUSE" -eq 1 ] && printf 渡す || printf 渡さない)"$'\n'
    else summary+="パーティション: ${PARTITION:-（クラスタの既定）} / GPU: $GPUS / FUSE: $([ "$ALLOW_FUSE" -eq 1 ] && printf 渡す || printf 渡さない)"$'\n'; fi
    summary+="秘密情報ファイル: ${SECRETS_FILE:-（渡さない）} / GitHub 仲介: ${GH_ENV_FILE:-（使わない）}"$'\n'
    summary+="追加の bind mount:"$'\n'
    if [ "${#EXTRA_BINDS[@]}" -eq 0 ]; then summary+="  なし"$'\n'
    else for arg in "${EXTRA_BINDS[@]}"; do summary+="  $arg"$'\n'; done; fi
    if [ -n "$OVERLAP_JOB" ]; then summary+="起動方法: srun --jobid=$OVERLAP_JOB --overlap --pty（実行中のジョブに重ねて$([ "$mode" = resume ] && printf '対話再開' || printf '対話起動')）"$'\n'
    elif [ "$mode" = resume ]; then summary+="起動方法: srun --pty（対話再開）"$'\n'
    else summary+="起動方法: $(if [ "$SUBMIT" -eq 1 ]; then printf 'sbatch（バッチ投入）'; elif [ "$mode" = assist ]; then printf 'srun --pty（対話）'; else printf '準備のみ（投入しない）'; fi)"$'\n'; fi
    summary+=$'\n'"wizard を使わずに同じ起動をするコマンド:"$'\n'"$command_line"$'\n'
    if [ "$WIZARD_DRY_RUN" -eq 1 ]; then wizard_finish_dry_run; return; fi
    if wizard_confirm "${summary}この設定で起動しますか？" 1; then
        wizard_save_last "$mode" "$profile" || return $?
        trap - INT TERM
        printf '\nwizard を使わずに同じ起動をするコマンド:\n  %s\n\n' "$command_line"
        finished=1 WIZARD_DONE=1
        # The wizard already displayed the complete configuration and obtained approval.
        local _AGENTRUN_RESUME_CONFIRMED=1
        if [ "$mode" = resume ]; then command_resume "${args[@]}"
        else command_prepare "$mode" "${args[@]}"; fi
    else
        rc=$?
        [ "$rc" -eq 1 ] || return "$rc"
        finished=1 WIZARD_DONE=1
        trap - INT TERM
        printf '起動を取りやめました。何も起動していません。\nこの設定で起動するコマンド:\n  %s\n' "$command_line"
    fi
}

# The launch part of the wizard (new runs and resume). command_wizard in wizard_tools.sh calls it.
# Returns 10 when the user goes back from the first step to the wizard's first menu.
wizard_launch() {
    ensure_default_secrets_file
    ensure_default_gh_env_file
    parse_run_args "$@"
    local -A RESUME_ENV_INPUT=()
    remember_review_environment
    local DEFAULT_GH_ENV_FILE="$DEFAULT_GH_ENV_FILE"
    local _RESUME_DEFAULT_GH_ENV_FILE="$DEFAULT_GH_ENV_FILE"
    local -a wizard_resume_overrides=()
    local -a wizard_original_args=("$@")
    local option_index option
    for ((option_index=0; option_index<${#wizard_original_args[@]}; option_index++)); do
        option="${wizard_original_args[option_index]}"
        case "$option" in
            --mem|--cpus|--time|--partition|--gpus|--repo|--goal|--secrets-file|--bind)
                wizard_resume_overrides+=("$option" "${wizard_original_args[option_index+1]}"); option_index=$((option_index+1)) ;;
            --no-binds|--allow-fuse|--no-allow-fuse|--no-secrets|--no-gh-broker|--gh-broker)
                wizard_resume_overrides+=("$option") ;;
            --agent) option_index=$((option_index+1)) ;;
            --) break ;;
        esac
    done
    local secrets_candidate="$SECRETS_FILE"
    local cli_mem="$MEM" cli_cpus="$CPUS" cli_time="$TIME_LIMIT" arg key
    WIZARD_EXPLICIT=()
    for arg in "$@"; do
        case "$arg" in --*) key="${arg#--}"; WIZARD_EXPLICIT["$key"]=1 ;; esac
    done
    wizard_load_last
    local same_dir=0
    [ "${WIZARD_LAST[cwd]:-}" != "$PWD" ] || same_dir=1
    for key in agent submit; do
        [ -n "${WIZARD_EXPLICIT[$key]:-}" ] && continue
        case "$key" in agent) AGENT="${WIZARD_LAST[agent]:-$AGENT}" ;; submit) SUBMIT="${WIZARD_LAST[submit]:-$SUBMIT}" ;; esac
    done
    [[ "$SUBMIT" =~ ^[01]$ ]] || SUBMIT=0
    is_supported_agent "$AGENT" || AGENT="$DEFAULT_AGENT"
    if [ -z "${WIZARD_EXPLICIT[bind]:-}" ]; then EXTRA_BINDS=("${WIZARD_LAST_BINDS[@]+"${WIZARD_LAST_BINDS[@]}"}"); fi
    if [ -z "${WIZARD_EXPLICIT[no-gh-broker]:-}" ] && [ "${WIZARD_LAST[gh_broker]:-1}" = 0 ]; then GH_BROKER_DISABLED=1; resolve_gh_broker; fi
    [ -n "${WIZARD_EXPLICIT[partition]:-}" ] || PARTITION="${WIZARD_LAST[partition]:-$PARTITION}"
    [ -n "${WIZARD_EXPLICIT[gpus]:-}" ] || GPUS="${WIZARD_LAST[gpus]:-$GPUS}"
    if [ -z "${WIZARD_EXPLICIT[allow-fuse]:-}${WIZARD_EXPLICIT[no-allow-fuse]:-}" ]; then ALLOW_FUSE="${WIZARD_LAST[allow_fuse]:-$ALLOW_FUSE}"; fi
    if [ -z "${WIZARD_EXPLICIT[secrets-file]:-}${WIZARD_EXPLICIT[no-secrets]:-}" ] && [ "${WIZARD_LAST[secrets]:-1}" = 0 ]; then SECRETS_FILE=''; fi
    if [ "$same_dir" -eq 1 ]; then
        [ -n "${WIZARD_EXPLICIT[repo]:-}" ] || REPO="${WIZARD_LAST[repo]:-$REPO}"
        [ -n "${WIZARD_EXPLICIT[goal]:-}" ] || GOAL="${WIZARD_LAST[goal]:-$GOAL}"
        [ -n "$PROMPT" ] || PROMPT="${WIZARD_LAST[prompt]:-}"
    fi
    wizard_banner 'agentrun の起動 — Enter で決定、:back で戻る、Ctrl+C・Esc・:cancel でキャンセル' || wizard_abort
    local mode='' profile='' source='' selected='' loaded_source='' step=0 rc=0 finished=0
    [ "$same_dir" -eq 0 ] || selected="${WIZARD_LAST[resume_id]:-}"
    local -a steps
    while [ "$finished" -eq 0 ]; do
        if [ "$mode" = resume ]; then steps=(mode session preview)
        else
            profile="$mode" steps=(mode)
            if [ -n "$mode" ] && wizard_templates_available; then steps+=(template)
            else WIZARD_TEMPLATE_KEEP=0; fi
            # An unchanged template skips straight to the overlap choice and confirmation.
            [ "$WIZARD_TEMPLATE_KEEP" -eq 1 ] || steps+=(agent launch)
        fi
        # Offer to join a running job only when one exists; resources then come from it.
        if wizard_overlap_available; then steps+=(overlap)
        elif [ -n "$mode" ]; then OVERLAP_JOB='' WIZARD_OVERLAP_INFO=''; fi
        if [ "$WIZARD_TEMPLATE_KEEP" -eq 1 ]; then
            if [ "$mode" != assist ] || [ "$SUBMIT" -eq 1 ]; then steps+=(prompt); else PROMPT=''; fi
            steps+=(confirm)
        else
        [ "$mode" = resume ] || steps+=(repo)
        if [ -z "$OVERLAP_JOB" ]; then
            [ "$mode" = resume ] || steps+=(partition gpus)
            steps+=(mem cpus time)
        fi
        steps+=(binds)
        [ "$mode" = resume ] || steps+=(fuse)
        if [ -f "$DEFAULT_GH_ENV_FILE" ] && file_sets_key "$DEFAULT_GH_ENV_FILE" GH_TOKEN; then steps+=(broker); fi
        if [ "$mode" != resume ]; then
            [ -z "$secrets_candidate" ] || steps+=(secrets)
            steps+=(goal)
            if [ "$mode" != assist ] || [ "$SUBMIT" -eq 1 ]; then steps+=(prompt); else PROMPT=''; fi
            steps+=(save)
        fi
        steps+=(confirm)
        fi
        rc=0
        wizard_step "${steps[step]}" || rc=$?
        case "$rc" in
            0) step=$((step + 1)) ;;
            11) ;;
            10)
                if [ "$step" -gt 0 ]; then step=$((step - 1))
                elif [ "$WIZARD_FROM_MENU" -eq 1 ]; then return 10; fi ;;
            130) wizard_abort ;;
            *) trap - INT TERM; return "$rc" ;;
        esac
    done
}

# Show what the launch would do (command_dry_run) and let the user launch it, change it or stop.
wizard_finish_dry_run() {
    local rc=0 next real='この設定で実際に起動する' change='設定を変更する（前の項目に戻る）' stop='wizard を終了する'
    if wizard_confirm "${summary}この設定で dry-run を実行しますか？（何も起動せず、run ディレクトリも作りません）" 1; then :
    else rc=$?; [ "$rc" -eq 1 ] && return 10; return "$rc"; fi
    wizard_exec "dry-run: agentrun dry-run $mode" wizard_cli dry-run "$mode" --show-mounts "${args[@]}" || return $?
    next="$(wizard_select 'dry-run の結果を確認しました。次はどうしますか？' "$real" "$change" "$stop")" || return $?
    case "$next" in
        "$real") WIZARD_DRY_RUN=0; return 11 ;;
        "$change") return 10 ;;
        *) finished=1 WIZARD_DONE=1; trap - INT TERM; printf 'dry-run だけで終了しました。起動はしていません。\n' ;;
    esac
}
