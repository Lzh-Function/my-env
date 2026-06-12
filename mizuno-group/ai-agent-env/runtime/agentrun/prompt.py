"""Capsule prompt rendering."""

from __future__ import annotations


def render_prompt(
    *,
    mode: str,
    agent: str,
    user_prompt: str,
    repo: str,
    goal: str | None = None,
    reviewers: str | None = None,
    target_diff: str | None = None,
    target_report: str | None = None,
    agents: str | None = None,
) -> str:
    lines = []
    if agent == "antigravity" and mode in ["experiment", "campaign"]:
        lines.append("/goal You are running inside an HPC agent capsule.")
    else:
        lines.append("You are running inside an HPC agent capsule.")
    
    lines.extend([
        "",
        f"Mode: {mode}",
        f"Agent: {agent}",
        "Workspace: /workspace",
        "Runs: /runs",
        "Scratch: /scratch",
        "Config: /home/sandbox/ai-agent-config",
        "",
        "User goal:",
        user_prompt,
        "",
        "Required live outputs:",
        "- /runs/live/status.json",
        "- /runs/live/heartbeat.txt",
        "- /runs/live/command_log.jsonl",
        "- /runs/live/current_task.md",
        "",
        "Required final outputs:",
        "- /runs/artifacts/report.md",
        "- /runs/artifacts/git_diff.patch",
        "- /runs/artifacts/metrics.json",
    ]
    optional = {
        "Goal file": goal,
        "Reviewers": reviewers,
        "Target diff": target_diff,
        "Target report": target_report,
        "Requested agents": agents,
    }
    for label, value in optional.items():
        if value:
            lines.extend(["", f"{label}: {value}"])
    lines.extend(["", f"Host repo: {repo}"])
    return "\n".join(lines) + "\n"

