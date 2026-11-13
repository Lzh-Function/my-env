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
    printf '\nwizard cancelled, nothing was launched\n' >&2
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
            choice="$("$DIALOG_BIN" --title 'agentrun wizard' --menu "$prompt" 20 90 12 "${menu_args[@]}" 3>&1 1>&2 2>&3)" || return 130
            ;;
        *)
            printf '\033[1;36m%s\033[0m\n' "$prompt" >&2
            wizard_readline_keys
            local n
            for n in "${!opts[@]}"; do printf '%d) %s\n' "$((n + 1))" "${opts[n]}" >&2; done
            while :; do
                read -e -r -p '#? (Enter=1, :back, :cancel) ' choice || return 130
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
        read -e -r -p "$prompt $suffix (:back, :cancel): " choice || return 130
        wizard_navigation "$choice" || return $?
        if [ -z "$choice" ]; then [ "$default_yes" -eq 1 ]; return; fi
        case "$choice" in y|Y|yes|Yes|YES) return 0 ;; *) return 1 ;; esac
    fi
    local -a opts=(Yes No)
    [ "$default_yes" -eq 1 ] || opts=(No Yes)
    choice="$(wizard_select "$prompt" "${opts[@]}")" || return $?
    [ "$choice" = Yes ]
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

wizard_valid_repo() {
    local path
    path="$(wizard_expand_tilde "${1:-.}")"
    [ -d "$path" ] || { printf 'repository path is not a directory: %s\n' "$1"; return 1; }
    path="$(readlink -f "$path")"
    if [ -n "${OVERLAP_JOB:-}" ] && repo_lock_busy "$path"; then
        printf 'agentrun is already active on %s; with overlap, choose another repository or a git worktree\n' "$path"
        return 1
    fi
    printf '%s\n' "$path"
}

wizard_valid_gpus() {
    [[ "$1" =~ ^[0-9]+$ ]] && [ "${#1}" -lt 9 ] || { printf 'GPU count must be a nonnegative integer\n'; return 1; }
    printf '%s\n' "$((10#$1))"
}

wizard_valid_mem() {
    [[ "$1" =~ ^[1-9][0-9]*[KMGTkmgt]?$ ]] || { printf 'memory must look like 16000M or 64G: %s\n' "$1"; return 1; }
    printf '%s\n' "$1"
}

wizard_valid_cpus() {
    [[ "$1" =~ ^[0-9]+$ ]] && [ "${#1}" -lt 9 ] && [ "$((10#$1))" -gt 0 ] || { printf 'CPU cores must be a positive integer: %s\n' "$1"; return 1; }
    printf '%s\n' "$((10#$1))"
}

wizard_valid_time() {
    [[ "$1" =~ ^([0-9]+-)?[0-9]+(:[0-5][0-9]){0,2}$ ]] || { printf 'walltime must look like HH:MM:SS, MM, or D-HH:MM:SS: %s\n' "$1"; return 1; }
    printf '%s\n' "$1"
}

wizard_valid_goal() {
    [ -n "$1" ] || { printf '\n'; return; }
    local path
    path="$(wizard_expand_tilde "$1")"
    [ -f "$path" ] || { printf 'goal file does not exist: %s\n' "$1"; return 1; }
    readlink -f "$path"
}

wizard_valid_path() {
    wizard_expand_tilde "$1"
}

wizard_valid_prompt() {
    [ -n "${1//[[:space:]]/}" ] || { printf 'a task prompt is required\n'; return 1; }
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
        goal "$GOAL" prompt "$PROMPT" reviewers "$REVIEWERS" target_diff "$TARGET_DIFF" target_report "$TARGET_REPORT" agents "$REQUESTED_AGENTS"
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
        [ "${#options[@]}" -gt 0 ] || options+=("$OVERLAP_JOB  (specified job)")
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
            WIZARD_OVERLAP_INFO="job ${info[0]}${info[7]:+ (${info[7]})} / node: ${info[4]} / partition: ${info[3]} / CPU: ${info[1]} / GPU: ${info[2]} / time limit: ${info[5]} (elapsed ${info[6]})"
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
                    if wizard_confirm 'Bind mounts: none. Add a bind mount?' 0; then stage=1
                    else rc=$?; [ "$rc" -ne 1 ] || return 0; return "$rc"; fi
                    continue
                fi
                choice="$(wizard_select "Bind mounts: ${EXTRA_BINDS[*]}" "$keep" "$add" "$remove_one" "$remove_all")" || return $?
                case "$choice" in
                    "$keep") return 0 ;;
                    "$add") stage=1 ;;
                    "$remove_one") stage=3 ;;
                    "$remove_all") EXTRA_BINDS=() ;;
                esac ;;
            1)
                src="$(wizard_path_input 'Bind mount source path on host' "$src")" || rc=$?
                [ "$rc" -ne 10 ] || { stage=0; continue; }
                [ "$rc" -eq 0 ] || return "$rc"
                src="$(wizard_expand_tilde "$src")"
                if [ -e "$src" ]; then src="$(readlink -f "$src")"; stage=2
                else wizard_banner "bind source does not exist: $src" || return $?; fi ;;
            2)
                dst="$(wizard_input 'Bind mount destination (e.g. /extra:ro)' "$dst")" || rc=$?
                [ "$rc" -ne 10 ] || { stage=1; continue; }
                [ "$rc" -eq 0 ] || return "$rc"
                if [[ "$dst" =~ ^/[^:,]+(:(ro|rw))?$ ]]; then EXTRA_BINDS+=("$src:$dst"); stage=0; src=''; dst=''
                else wizard_banner 'destination must be an absolute path with optional :ro or :rw' || return $?; fi ;;
            3)
                choice="$(wizard_select 'Select a bind mount to remove' "${EXTRA_BINDS[@]}")" || rc=$?
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
    local step="$1" choice rc=0 fields preview default key
    case "$step" in
        mode)
            local -a modes=()
            default="${mode:-${TEMPLATE_MODE:-${WIZARD_LAST[mode]:-assist}}}"
            if is_profile "$default" || [ "$default" = resume ]; then modes+=("$default"); fi
            for choice in assist experiment campaign review multi-review resume; do [ "$choice" = "$default" ] || modes+=("$choice"); done
            choice="$(wizard_select 'Select run mode' "${modes[@]}" "$WIZARD_MANAGE_TEMPLATES")" || return $?
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
            choice="$(wizard_select 'Select agent' "${agents[@]}")" || return $?
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
                local -a launches=('Interactive session (srun --pty)' 'Batch submit (sbatch)')
                [ "$SUBMIT" -eq 0 ] || launches=('Batch submit (sbatch)' 'Interactive session (srun --pty)')
                choice="$(wizard_select 'Select launch style' "${launches[@]}")" || return $?
                case "$choice" in 'Batch submit (sbatch)') SUBMIT=1 ;; *) SUBMIT=0 ;; esac
            else
                if wizard_confirm 'Submit this job now via sbatch?' "$SUBMIT"; then SUBMIT=1
                else rc=$?; [ "$rc" -eq 1 ] || return "$rc"; SUBMIT=0; fi
            fi ;;
        repo) wizard_ask REPO 'Repository path' "$REPO" wizard_valid_repo ;;
        mem) wizard_ask MEM 'Memory (e.g. 16000M, 64G)' "$(wizard_resource_default mem "$profile" "$MEM")" wizard_valid_mem ;;
        cpus) wizard_ask CPUS 'CPU cores' "$(wizard_resource_default cpus "$profile" "$CPUS")" wizard_valid_cpus ;;
        time) wizard_ask TIME_LIMIT 'Walltime (HH:MM:SS or D-HH:MM:SS)' "$(wizard_resource_default time "$profile" "$TIME_LIMIT")" wizard_valid_time ;;
        partition) wizard_ask PARTITION 'Slurm partition (empty for cluster default)' "$PARTITION" ;;
        gpus) wizard_ask GPUS 'GPU count' "$GPUS" wizard_valid_gpus ;;
        fuse)
            if wizard_confirm 'Bind /dev/fuse into the capsule?' "$ALLOW_FUSE"; then ALLOW_FUSE=1
            else rc=$?; [ "$rc" -eq 1 ] || return "$rc"; ALLOW_FUSE=0; fi ;;
        secrets)
            if wizard_confirm "Pass secrets from $secrets_candidate into the capsule?" "$(secrets_enabled && printf 1 || printf 0)"; then SECRETS_FILE="$secrets_candidate"
            else rc=$?; [ "$rc" -eq 1 ] || return "$rc"; SECRETS_FILE=''; fi ;;
        binds) wizard_bind_mounts ;;
        template) wizard_template ;;
        save) wizard_template_save ;;
        overlap) wizard_overlap ;;
        broker)
            if wizard_confirm 'Start the GitHub CLI broker? (token stays outside the agent capsule)' "$((1 - GH_BROKER_DISABLED))"; then GH_BROKER_DISABLED=0
            else rc=$?; [ "$rc" -eq 1 ] || return "$rc"; GH_BROKER_DISABLED=1; fi
            resolve_gh_broker ;;
        goal) wizard_ask GOAL 'Goal file path (optional, empty to skip)' "$GOAL" wizard_valid_goal ;;
        prompt)
            if [ "$mode" = assist ] && [ "$SUBMIT" -eq 0 ]; then PROMPT=''
            else wizard_ask PROMPT 'Task prompt' "$PROMPT" wizard_valid_prompt; fi ;;
        reviewers) wizard_ask REVIEWERS 'Reviewers (codex,claude; comma-separated)' "$REVIEWERS" validate_agent_list ;;
        target_diff) wizard_ask TARGET_DIFF 'Target diff path' "$TARGET_DIFF" wizard_valid_path ;;
        target_report) wizard_ask TARGET_REPORT 'Target report path' "$TARGET_REPORT" wizard_valid_path ;;
        agents) wizard_ask REQUESTED_AGENTS 'Multi-review agents (codex,claude; comma-separated)' "$REQUESTED_AGENTS" validate_agent_list ;;
        confirm) wizard_finish ;;
    esac
}

wizard_finish() {
    local -a args
    if [ -n "$OVERLAP_JOB" ] && [ "$mode" != resume ] && repo_lock_busy "$(readlink -f "$REPO")"; then
        wizard_banner "agentrun is already active on $REPO; with overlap, choose another repository or a git worktree" || return $?
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
    [ -z "$REVIEWERS" ] || args+=(--reviewers "$REVIEWERS")
    [ -z "$TARGET_DIFF" ] || args+=(--target-diff "$TARGET_DIFF")
    [ -z "$TARGET_REPORT" ] || args+=(--target-report "$TARGET_REPORT")
    [ -z "$REQUESTED_AGENTS" ] || args+=(--agents "$REQUESTED_AGENTS")
    if [ "$mode" != resume ]; then
        [ "$SUBMIT" -eq 0 ] || args+=(--submit)
        [ -z "$PROMPT" ] || args+=(-- "$PROMPT")
    fi
    local command_line="agentrun $mode" summary rc=0 key prefix=''
    for key in AGENT_REVIEW_CODEX_MODEL AGENT_REVIEW_CODEX_EFFORT AGENT_REVIEW_CLAUDE_MODEL AGENT_REVIEW_CLAUDE_EFFORT \
        AGENT_REVIEW_ACTIVE_TIMEOUT; do
        [ -z "${!key:-}" ] || prefix+="$key=$(wizard_shell_quote "${!key}") "
    done
    [ -z "$prefix" ] || command_line="env $prefix$command_line"
    for arg in "${args[@]}"; do command_line+=" $(wizard_shell_quote "$arg")"; done
    summary="mode: $mode / agent: $AGENT / profile: $profile"$'\n'"repo: $REPO"$'\n'
    [ -z "$TEMPLATE_NAME" ] || [ "$mode" = resume ] || summary+="template: $TEMPLATE_NAME$([ "$WIZARD_TEMPLATE_KEEP" -eq 1 ] && printf '（変更なし）' || printf '（変更あり）')"$'\n'
    if [ -n "$OVERLAP_JOB" ]; then
        summary+="overlap: ${WIZARD_OVERLAP_INFO:-job $OVERLAP_JOB}"$'\n'
        summary+="  CPU・メモリ・GPU・制限時間は元のジョブと共有し、元のジョブが終わるとこのコンテナも終了します"$'\n'
    else summary+="mem/cpus/time: $MEM / $CPUS / $TIME_LIMIT"$'\n'; fi
    [ "$mode" != resume ] || summary+="再開対象: $selected"$'\n'"$(settings_tool describe "$source")"$'\n'
    if [ -n "$OVERLAP_JOB" ]; then summary+="FUSE: $ALLOW_FUSE"$'\n'
    else summary+="partition: ${PARTITION:-<cluster default>} / GPU: $GPUS / FUSE: $ALLOW_FUSE"$'\n'; fi
    summary+="secrets file: ${SECRETS_FILE:-<none>} / gh broker: ${GH_ENV_FILE:-<disabled>}"$'\n'
    summary+="extra bind mounts:"$'\n'
    if [ "${#EXTRA_BINDS[@]}" -eq 0 ]; then summary+="  <none>"$'\n'
    else for arg in "${EXTRA_BINDS[@]}"; do summary+="  $arg"$'\n'; done; fi
    if [ -n "$OVERLAP_JOB" ]; then summary+="launch: srun --jobid=$OVERLAP_JOB --overlap --pty（実行中のジョブに重ねて$([ "$mode" = resume ] && printf '対話再開' || printf '対話起動')）"$'\n'
    elif [ "$mode" = resume ]; then summary+="launch: srun --pty（対話再開）"$'\n'
    else summary+="launch: $(if [ "$SUBMIT" -eq 1 ]; then printf sbatch; elif [ "$mode" = assist ]; then printf 'srun --pty'; else printf 'prepare only'; fi)"$'\n'; fi
    summary+=$'\n'"Same run without the wizard:"$'\n'"$command_line"$'\n'
    if wizard_confirm "${summary}Launch this run?" 1; then
        wizard_save_last "$mode" "$profile" || return $?
        trap - INT TERM
        printf '\nSame run without the wizard:\n  %s\n\n' "$command_line"
        finished=1
        # The wizard already displayed the complete configuration and obtained approval.
        local _AGENTRUN_RESUME_CONFIRMED=1
        if [ "$mode" = resume ]; then command_resume "${args[@]}"
        else command_prepare "$mode" "${args[@]}"; fi
    else
        rc=$?
        [ "$rc" -eq 1 ] || return "$rc"
        finished=1
        trap - INT TERM
        printf 'aborted, nothing was launched\nCommand for these settings:\n  %s\n' "$command_line"
    fi
}

command_wizard() {
    [ -t 0 ] && [ -t 1 ] || { printf 'agentrun wizard requires an interactive terminal\n' >&2; return 1; }
    detect_wizard_ui
    trap wizard_abort INT TERM
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
            --mem|--cpus|--time|--partition|--gpus|--repo|--goal|--secrets-file|--bind|--reviewers|--agents|--target-diff|--target-report)
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
    for key in agent submit agents; do
        [ -n "${WIZARD_EXPLICIT[$key]:-}" ] && continue
        case "$key" in agent) AGENT="${WIZARD_LAST[agent]:-$AGENT}" ;; submit) SUBMIT="${WIZARD_LAST[submit]:-$SUBMIT}" ;; agents) REQUESTED_AGENTS="${WIZARD_LAST[agents]:-$REQUESTED_AGENTS}" ;; esac
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
        [ -n "${WIZARD_EXPLICIT[reviewers]:-}" ] || REVIEWERS="${WIZARD_LAST[reviewers]:-}"
        [ -n "${WIZARD_EXPLICIT[target-diff]:-}" ] || TARGET_DIFF="${WIZARD_LAST[target_diff]:-}"
        [ -n "${WIZARD_EXPLICIT[target-report]:-}" ] || TARGET_REPORT="${WIZARD_LAST[target_report]:-}"
    fi
    validate_agent_list "$REQUESTED_AGENTS" 2>/dev/null || REQUESTED_AGENTS=''
    validate_agent_list "$REVIEWERS" 2>/dev/null || REVIEWERS=''
    wizard_banner 'agentrun wizard - Enter accepts the value; :back goes back; Ctrl+C / Esc / :cancel cancels' || wizard_abort
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
            case "$mode" in review) steps+=(reviewers target_diff target_report) ;; multi-review) steps+=(agents) ;; esac
            steps+=(save)
        fi
        steps+=(confirm)
        fi
        rc=0
        wizard_step "${steps[step]}" || rc=$?
        case "$rc" in
            0) step=$((step + 1)) ;;
            11) ;;
            10) [ "$step" -eq 0 ] || step=$((step - 1)) ;;
            130) wizard_abort ;;
            *) trap - INT TERM; return "$rc" ;;
        esac
    done
}
