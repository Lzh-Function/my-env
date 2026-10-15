# Bash completion for host paths. Source this file, or use bash-completion's
# ~/.local/share/bash-completion/completions/agentrun loader.

_agentrun_unquote_path() {
    # COMP_WORDS retains shell quoting. Decode it without eval or expansion.
    local text="$1" state='' char next i
    REPLY=''
    for ((i=0; i<${#text}; i++)); do
        char="${text:i:1}"
        case "$state" in
            single)
                if [ "$char" = "'" ]; then state=''; else REPLY+="$char"; fi ;;
            double)
                case "$char" in
                    '"') state='' ;;
                    '\')
                        next="${text:i+1:1}"
                        case "$next" in '$'|'`'|'"'|'\') REPLY+="$next"; i=$((i+1)) ;; *) REPLY+="$char" ;; esac ;;
                    *) REPLY+="$char" ;;
                esac ;;
            *)
                case "$char" in
                    "'") state=single ;;
                    '"') state=double ;;
                    '\') i=$((i+1)); REPLY+="${text:i:1}" ;;
                    *) REPLY+="$char" ;;
                esac ;;
        esac
    done
}

_agentrun_complete() {
    COMPREPLY=()
    local current="${COMP_WORDS[COMP_CWORD]}" previous="${COMP_WORDS[COMP_CWORD-1]:-}" REPLY candidate
    case "$previous" in
        --bind|--repo|--goal) ;;
        *) return 0 ;;
    esac
    _agentrun_unquote_path "$current"
    # --bind SRC:DST:OPTIONS: only SRC names a host path.
    if [ "$previous" = --bind ] && [[ "$REPLY" == *:* ]]; then return 0; fi
    case "$REPLY" in '~') REPLY="$HOME/" ;; '~/'*) REPLY="$HOME/${REPLY:2}" ;; esac
    compopt -o filenames -o nospace
    while IFS= read -r candidate; do
        COMPREPLY+=("$candidate")
    done < <(compgen -f -- "$REPLY")
}

complete -o default -F _agentrun_complete agentrun
