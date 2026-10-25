#!/usr/bin/env bash
# Native CLI + real Apptainer/MCP. All model responses are local fixtures.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
package="${1:?usage: native-codex-review-smoke.sh CODEX_PACKAGE_DIR TEST_IMAGE}"
test_image="${2:?pass a Docker image built by tests/slurm/docker/run.sh}"
package="$(cd "$package" && pwd -P)"
test -x "$package/bin/codex"
docker run --rm --interactive --privileged --network none \
    --mount "type=bind,src=$package,dst=/opt/native-codex,readonly" \
    --mount "type=bind,src=$root/runtime/agentrun,dst=/opt/current-runtime,readonly" \
    --mount "type=bind,src=$root/tests/slurm/native-codex-review-probe.py,dst=/opt/native-probe.py,readonly" \
    --entrypoint /bin/bash "$test_image" -s <<'SH'
set -euo pipefail
mkdir -p /tmp/native-home
chown capsule:capsule /tmp/native-home
runuser -u capsule -- apptainer exec --containall --cleanenv \
    --no-mount hostfs,bind-paths,cwd --pwd /workspace \
    --home /tmp/native-home:/home/sandbox \
    --bind /opt/native-codex:/opt/native-codex:ro \
    --bind /opt/current-runtime:/opt/current-runtime:ro \
    --bind /opt/native-probe.py:/opt/native-probe.py:ro \
    --bind /dev/full:/dev/full \
    /opt/agent-root /opt/test-deps/bin/python /opt/native-probe.py \
    /opt/native-codex/bin/codex /opt/current-runtime
SH
