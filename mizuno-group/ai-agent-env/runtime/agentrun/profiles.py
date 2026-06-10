"""Runtime profile definitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceProfile:
    name: str
    cpus: int
    memory: str
    time: str
    gpus: int = 0
    require_human_approval: bool = False


PROFILES = {
    "assist": ResourceProfile("assist", cpus=4, memory="32000M", time="01:00:00"),
    "experiment": ResourceProfile("experiment", cpus=8, memory="64000M", time="04:00:00"),
    "campaign": ResourceProfile("campaign", cpus=8, memory="64000M", time="04:00:00", require_human_approval=True),
    "review": ResourceProfile("review", cpus=4, memory="16000M", time="01:00:00"),
    "multi-review": ResourceProfile("multi-review", cpus=4, memory="32000M", time="02:00:00"),
}


def get_profile(name: str) -> ResourceProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"unknown profile: {name}") from exc

