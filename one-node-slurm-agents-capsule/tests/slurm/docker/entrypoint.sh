#!/usr/bin/env bash
set -euo pipefail
role="${1:?controller or compute}"
install -d -o munge -g munge -m 755 /run/munge /var/log/munge /var/lib/munge
if [ "$role" = controller ]; then
    # Production parent has neither Apptainer nor an agent CLI installed.
    rm -f /usr/bin/apptainer /usr/bin/singularity
    if [ ! -s /cluster-auth/munge.key ]; then
        (umask 077; head -c 1024 /dev/urandom > /cluster-auth/munge.key)
    fi
    mkdir -p /shared/capsule
    cp -r /opt/capsule/. /shared/capsule/
    chown -R capsule:capsule /shared/capsule
    install -d -o capsule -g capsule -m 700 /shared/work /shared/user-state /shared/user-state/1000 /shared/history
    touch /shared/source-ready
else
    for attempt in {1..120}; do
        [ ! -f /shared/source-ready ] || break
        sleep 1
    done
    test -f /shared/source-ready
    # Same UID, different username, and no controller HOME on compute.
    usermod -l worker -d /home/worker capsule
    rm -rf /home/capsule
    install -d -m 1777 /scratch
    install -d -o worker -g capsule -m 700 /scratch/capsule
    printf "node-local SSD\n" > /scratch/capsule/node-marker.txt
    chown worker:capsule /scratch/capsule/node-marker.txt
    apptainer build --force /shared/capsule/runtime/apptainer/base-system.sif /opt/agent-root
    chmod 644 /shared/capsule/runtime/apptainer/base-system.sif
    # Only modify this container's private cgroup namespace, never the host tree.
    grep -qx '0::/' /proc/1/cgroup
    mkdir -p /sys/fs/cgroup/init.scope /sys/fs/cgroup/system.slice
    readarray -t bootstrap_pids < /sys/fs/cgroup/cgroup.procs
    for pid in "${bootstrap_pids[@]}"; do
        printf '%s\n' "$pid" > /sys/fs/cgroup/init.scope/cgroup.procs 2>/dev/null || true
    done
    printf '+cpu +cpuset +memory\n' > /sys/fs/cgroup/cgroup.subtree_control
fi
install -o munge -g munge -m 400 /cluster-auth/munge.key /etc/munge/munge.key
runuser -u munge -- munged --foreground &
for attempt in {1..100}; do
    [ ! -S /run/munge/munge.socket.2 ] || break
    sleep 0.1
done
if [ "$role" = controller ]; then
    exec slurmctld -D -vv
else
    exec slurmd -D -vv
fi
