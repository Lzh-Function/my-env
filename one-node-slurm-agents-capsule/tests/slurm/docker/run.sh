#!/usr/bin/env bash
# Creates and removes only this invocation's Docker Compose resources.
set -euo pipefail
root="$(cd "$(dirname "$0")/../../.." && pwd)"
project="one-node-slurm-$(date +%s)-$$"
remove_image=0
[ -n "${SLURM_TEST_IMAGE_TAG:-}" ] || remove_image=1
export SLURM_TEST_IMAGE_TAG="${SLURM_TEST_IMAGE_TAG:-$project}"
compose=(docker compose -p "$project" -f "$root/tests/slurm/docker/compose.yaml")
artifacts="${SLURM_TEST_ARTIFACTS:-$root/.agent-runs/$project}"
mkdir -p "$artifacts"
cleanup() {
    local rc=$?
    trap - EXIT
    "${compose[@]}" logs --no-color > "$artifacts/cluster.log" 2>&1 || true
    "${compose[@]}" cp controller:/shared/work "$artifacts/work" >/dev/null 2>&1 || true
    "${compose[@]}" cp controller:/shared/history "$artifacts/history" >/dev/null 2>&1 || true
    "${compose[@]}" down --volumes --remove-orphans --timeout 10 || true
    if [ "$remove_image" -eq 1 ]; then
        docker image rm "one-node-capsule-slurm-test:$SLURM_TEST_IMAGE_TAG" >/dev/null 2>&1 || true
    fi
    if [ "$rc" -ne 0 ]; then tail -n 150 "$artifacts/cluster.log"; fi
    printf 'Docker Slurm test artifacts: %s\n' "$artifacts"
    exit "$rc"
}
trap cleanup EXIT
"${compose[@]}" build controller 2>&1 | tee "$artifacts/build.log"
"${compose[@]}" up --detach --wait --wait-timeout 240 2>&1 | tee "$artifacts/startup.log"
"${compose[@]}" exec -T --user capsule controller \
    /opt/test-deps/bin/python /opt/cluster-test/test_cluster.py "$@" 2>&1 | tee "$artifacts/tests.log"
"${compose[@]}" exec -T --user capsule --workdir /shared/capsule controller \
    /opt/test-deps/bin/python -m unittest discover -s tests -p 'test_*.py' -v 2>&1 | tee "$artifacts/unit-tests.log"
