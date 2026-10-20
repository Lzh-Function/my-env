# syntax=docker/dockerfile:1
FROM ubuntu:24.04 AS agent-root
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates coreutils git jq python3 python3-venv && \
    python3 -m venv /opt/test-deps && \
    /opt/test-deps/bin/pip install --no-cache-dir uv==0.9.5 mcp==1.26.0 pyyaml==6.0.3 && \
    ln -s /opt/test-deps/bin/uv /usr/local/bin/uv && \
    UV_CACHE_DIR=/opt/test-uv-cache /usr/local/bin/uv run --no-project \
        --python /usr/bin/python3 --with mcp==1.26.0 python -c 'import mcp' && \
    rm -rf /var/lib/apt/lists/*
COPY tests/slurm/docker/fixtures/curl.py /usr/local/bin/curl
COPY tests/slurm/docker/fixtures/agent.py /opt/capsule-test/agent.py
COPY tests/slurm/docker/fixtures/features.py /opt/capsule-test/features.py
COPY tests/slurm/docker/fixtures/gh.py /usr/bin/gh
RUN chmod 755 /usr/local/bin/curl /opt/capsule-test/agent.py /usr/bin/gh && \
    mkdir -p /workspace /runs /scratch /cache /output /home/sandbox/.local/bin \
        /etc/codex && touch /etc/codex/requirements.toml

FROM ubuntu:24.04
ARG SLURM_PACKAGE_VERSION=23.11.4-1.2ubuntu5
ARG APPTAINER_VERSION=1.5.3
ARG APPTAINER_SHA256=82b0bdddf459087d202383360b8318d526ad6826c748a2f669913cc6aef9ee40
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    "slurmctld=${SLURM_PACKAGE_VERSION}" "slurmd=${SLURM_PACKAGE_VERSION}" \
    "slurm-client=${SLURM_PACKAGE_VERSION}" munge bash ca-certificates coreutils \
    curl git jq python3 squashfs-tools tini uidmap && \
    curl -fLSs --retry 2 --max-time 180 \
        "https://github.com/apptainer/apptainer/releases/download/v${APPTAINER_VERSION}/apptainer_${APPTAINER_VERSION}_amd64.deb" \
        -o /tmp/apptainer.deb && \
    echo "${APPTAINER_SHA256}  /tmp/apptainer.deb" | sha256sum -c - && \
    apt-get install -y --no-install-recommends /tmp/apptainer.deb && \
    rm -f /tmp/apptainer.deb && rm -rf /var/lib/apt/lists/*
RUN userdel -r ubuntu && useradd --uid 1000 --create-home --shell /bin/bash capsule
COPY --from=agent-root / /opt/agent-root/
COPY --from=agent-root /opt/test-deps /opt/test-deps
COPY runtime /opt/capsule/runtime
COPY agents /opt/capsule/agents
COPY common /opt/capsule/common
COPY profiles /opt/capsule/profiles
COPY templates /opt/capsule/templates
COPY tests /opt/capsule/tests
COPY install.sh uninstall.sh /opt/capsule/
COPY secrets/.env.example secrets/gh.env.example /opt/capsule/secrets/
COPY tests/slurm/docker /opt/cluster-test
COPY tests/slurm/docker/slurm.conf /etc/slurm/slurm.conf
COPY tests/slurm/docker/cgroup.conf /etc/slurm/cgroup.conf
RUN chmod 755 /opt/cluster-test/entrypoint.sh && \
    mkdir -p /shared /cluster-auth /var/spool/slurmctld /var/spool/slurmd && \
    chown slurm:slurm /var/spool/slurmctld && touch /etc/capsule-test-cluster
ENV AGENTRUN_HISTORY_DIR=/shared/history \
    SLURM_CONF=/etc/slurm/slurm.conf
ENTRYPOINT ["/usr/bin/tini", "--", "/opt/cluster-test/entrypoint.sh"]
