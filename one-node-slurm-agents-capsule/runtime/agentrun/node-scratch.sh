#!/usr/bin/env bash

# Called on the compute node; the submission host need not see this directory.
_agentrun_node_scratch_setup() {
    local source_path="$1"
    AGENTRUN_NODE_SCRATCH_ARGS=(--env AGENTRUN_NODE_SCRATCH=)
    if [ -d "$source_path" ]; then
        AGENTRUN_NODE_SCRATCH_ARGS=(
            --bind "$source_path:/node-scratch:rw"
            --env AGENTRUN_NODE_SCRATCH=/node-scratch
        )
        printf 'agentrun: compute-node SSD %s -> /node-scratch\n' "$source_path" >&2
    fi
}
