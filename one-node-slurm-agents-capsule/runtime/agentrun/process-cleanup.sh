# host/compute nodeの補助processを、終了codeを保って有限時間で停止する。
_agentrun_cleanup_home() {
    local run_dir="$1" attempt
    # NFS silly-renamed files can remain briefly after the job exits. Preserve
    # rm diagnostics and retry, inside the caller's existing 15-second timeout.
    for attempt in {1..5}; do
        if rm -rf -- "$run_dir/home" 2>>"$run_dir/live/home_cleanup.log"; then
            return 0
        fi
        printf 'home cleanup attempt %s failed\n' "$attempt" >> "$run_dir/live/home_cleanup.log"
        [ "$attempt" -eq 5 ] || sleep 0.5
    done
    return 1
}

_agentrun_stop_process() {
    local pid="$1" label="$2" attempt
    kill -TERM "$pid" 2>/dev/null || true
    for attempt in {1..50}; do
        if ! kill -0 "$pid" 2>/dev/null; then
            wait "$pid" 2>/dev/null
            return $?
        fi
        sleep 0.1 200>&-
    done
    printf '%sが5秒以内に終了しないため、強制停止します。\n' "$label" >&2
    kill -KILL "$pid" 2>/dev/null || true
    # kill後もD state等のprocessをwaitして終了処理を止めない。
    return 124
}
