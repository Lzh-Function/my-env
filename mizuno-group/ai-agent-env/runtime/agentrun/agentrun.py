#!/usr/bin/env python3
"""Minimal agentrun launcher scaffold for the mizuno-group agent environment."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from adapters import ADAPTERS, get_adapter
from artifacts import PROFILE_REQUIRED_OUTPUTS, REQUIRED_OUTPUTS
from profiles import PROFILES as PROFILE_DEFS
from profiles import get_profile
from prompt import render_prompt
from slurm import SlurmRequest, build_srun


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AGENT = "antigravity"
AGENTS = {name: list(adapter.command_candidates) for name, adapter in ADAPTERS.items()}
PROFILES = set(PROFILE_DEFS)


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def print_checks(checks: list[Check]) -> int:
    failed = False
    for check in checks:
        marker = "OK" if check.ok else "FAIL"
        detail = f" - {check.detail}" if check.detail else ""
        print(f"[{marker}] {check.name}{detail}")
        failed = failed or not check.ok
    return 1 if failed else 0


def required_paths() -> list[Path]:
    paths = [
        ROOT / "common" / "AGENTS.md",
        ROOT / "claude" / "CLAUDE.md",
        ROOT / "claude" / "settings.json",
        ROOT / "agents" / "claude" / "CLAUDE.md",
        ROOT / "agents" / "claude" / "settings.json",
        ROOT / "agents" / "claude" / "settings.assist.json",
        ROOT / "agents" / "claude" / "settings.experiment.json",
        ROOT / "agents" / "codex" / "AGENTS.md",
        ROOT / "agents" / "codex" / "config.toml",
        ROOT / "agents" / "codex" / "config.assist.toml",
        ROOT / "agents" / "codex" / "config.experiment.toml",
        ROOT / "agents" / "antigravity" / "AGENTS.md",
        ROOT / "agents" / "antigravity" / "GEMINI.md",
        ROOT / "runtime" / "apptainer" / "base-system.def",
        ROOT / "runtime" / "apptainer" / "base-agent.def",
    ]
    for profile in PROFILES:
        paths.append(ROOT / "profiles" / f"{profile}.yaml")
    return paths


def validate_json(path: Path) -> Check:
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return Check(str(path.relative_to(ROOT)), False, str(exc))
    return Check(str(path.relative_to(ROOT)), True)


def validate_toml(path: Path) -> Check:
    try:
        tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return Check(str(path.relative_to(ROOT)), False, str(exc))
    return Check(str(path.relative_to(ROOT)), True)


def command_validate(args: argparse.Namespace) -> int:
    checks: list[Check] = []
    for path in required_paths():
        checks.append(Check(str(path.relative_to(ROOT)), path.exists()))

    for path in sorted(ROOT.rglob("*.json")):
        if ".agent-runs" not in path.parts:
            checks.append(validate_json(path))

    for path in sorted(ROOT.rglob("*.toml")):
        checks.append(validate_toml(path))

    for hook in sorted((ROOT / "claude" / "hooks").glob("*.sh")):
        checks.append(Check(str(hook.relative_to(ROOT)), os.access(hook, os.X_OK), "must be executable"))

    for hook in sorted((ROOT / "common" / "hooks").glob("*.py")):
        checks.append(Check(str(hook.relative_to(ROOT)), os.access(hook, os.X_OK), "must be executable"))

    return print_checks(checks)


def which_any(candidates: list[str]) -> str | None:
    for command in candidates:
        found = shutil.which(command)
        if found:
            return found
    return None


def command_doctor(args: argparse.Namespace) -> int:
    checks = [
        Check("config root", ROOT.exists(), str(ROOT)),
        Check("run directory writable", os.access(Path.cwd(), os.W_OK), str(Path.cwd() / ".agent-runs")),
    ]

    for command in ["sinfo", "squeue", "srun", "sbatch", "apptainer", "uv"]:
        found = shutil.which(command)
        checks.append(Check(f"command:{command}", bool(found), found or "not found"))

    selected = list(AGENTS) if args.all else [args.agent or DEFAULT_AGENT]
    for agent in selected:
        found = which_any(AGENTS[agent])
        checks.append(Check(f"agent:{agent}", bool(found), found or "not found"))

    auth_paths = {
        "claude": [Path.home() / ".claude", Path.home() / ".claude.json"],
        "codex": [Path.home() / ".codex" / "auth.json"],
        "antigravity": [Path.home() / ".gemini", Path.home() / ".antigravity"],
    }
    for agent in selected:
        present = [str(path) for path in auth_paths[agent] if path.exists()]
        checks.append(Check(f"auth:{agent}", bool(present), ", ".join(present) if present else "not found"))

    return print_checks(checks)


def command_agents(args: argparse.Namespace) -> int:
    print("Available agents:")
    for name in sorted(ADAPTERS):
        adapter = get_adapter(name)
        found = which_any(list(adapter.command_candidates))
        state = "available" if found else "missing"
        detail = found or ",".join(adapter.command_candidates)
        print(f"  {name:<12} {adapter.role:<9} {state:<9} {detail}")
    return 0


def build_run_id(mode: str, agent: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{mode}_{agent}"


def build_prompt(args: argparse.Namespace, agent: str, user_prompt: str) -> str:
    return render_prompt(
        mode=args.mode,
        agent=agent,
        user_prompt=user_prompt,
        repo=args.repo,
        goal=args.goal,
        reviewers=args.reviewers,
        target_diff=args.target_diff,
        target_report=args.target_report,
        agents=args.agents,
    )


def build_slurm_command(args: argparse.Namespace) -> list[str]:
    profile = get_profile(args.mode)
    request = SlurmRequest(
        mode=args.mode,
        agent=args.agent or DEFAULT_AGENT,
        cpus=profile.cpus,
        memory=profile.memory,
        time=args.time or profile.time,
        gpus=args.gpus,
    )
    return build_srun(request)


def build_apptainer_command(args: argparse.Namespace, run_dir: Path) -> list[str]:
    adapter = get_adapter(args.agent or DEFAULT_AGENT)
    agent_command = adapter.build_command("/runs/prompt.txt", args.mode)
    image = str(ROOT / "runtime" / "apptainer" / "base-agent.sif")
    command = ["apptainer", "exec"]
    if args.gpus:
        command.append("--nv")
    command.extend(
        [
            "--containall",
            "--cleanenv",
            "--home",
            f"{run_dir / 'home'}:/home/sandbox",
            "--bind",
            f"{run_dir / 'workspace'}:/workspace:rw",
            "--bind",
            f"{run_dir}:/runs:rw",
            "--bind",
            f"{run_dir / 'scratch'}:/scratch:rw",
            "--bind",
            f"{run_dir / 'cache'}:/cache:rw",
            "--bind",
            f"{ROOT}:/home/sandbox/ai-agent-config:ro",
        ]
    )
    for auth in adapter.auth_paths:
        if auth.host_path.exists():
            mode = "rw" if auth.writable else "ro"
            command.extend(["--bind", f"{auth.host_path}:{auth.container_path}:{mode}"])
    for mount in home_config_mounts(agent=adapter.name):
        command.extend(["--bind", mount])
    command.append(image)
    command.extend(["bash", "-l", "-c", shlex.join(agent_command)])
    return command


def home_config_mounts(agent: str) -> list[str]:
    if agent == "claude":
        return [
            f"{ROOT / 'agents' / 'claude' / 'CLAUDE.md'}:/home/sandbox/.claude/CLAUDE.md:ro",
            f"{ROOT / 'agents' / 'claude' / 'settings.json'}:/home/sandbox/.claude/settings.json:ro",
            f"{ROOT / 'common' / 'hooks'}:/home/sandbox/.claude/hooks:ro",
            f"{ROOT / 'agents' / 'claude' / 'skills'}:/home/sandbox/.claude/skills:ro",
        ]
    if agent == "codex":
        return [
            f"{ROOT / 'agents' / 'codex' / 'config.toml'}:/home/sandbox/.codex/config.toml:ro",
            f"{ROOT / 'agents' / 'codex' / 'hooks.json'}:/home/sandbox/.codex/hooks.json:ro",
            f"{ROOT / 'agents' / 'codex' / 'AGENTS.md'}:/home/sandbox/.codex/AGENTS.md:ro",
            f"{ROOT / 'agents' / 'codex' / 'skills'}:/home/sandbox/.agents/skills:ro",
        ]
    if agent == "antigravity":
        return [
            f"{ROOT / 'agents' / 'antigravity' / 'settings.json'}:/home/sandbox/.gemini/settings.json:ro",
            f"{ROOT / 'agents' / 'antigravity' / 'GEMINI.md'}:/home/sandbox/.gemini/GEMINI.md:ro",
            f"{ROOT / 'agents' / 'antigravity' / 'AGENTS.md'}:/home/sandbox/.gemini/AGENTS.md:ro",
        ]
    return []


def command_dry_run(args: argparse.Namespace) -> int:
    agent = args.agent or DEFAULT_AGENT
    adapter = get_adapter(agent)
    run_id = build_run_id(args.mode, agent)
    run_dir = Path.cwd() / ".agent-runs" / run_id
    prompt = build_prompt(args, agent, args.prompt)
    agent_command = adapter.build_command("/runs/prompt.txt", args.mode)
    capsule = {
        "run_id": run_id,
        "mode": args.mode,
        "agent": agent,
        "repo": args.repo,
        "goal": args.goal,
        "reviewers": args.reviewers,
        "target_diff": args.target_diff,
        "target_report": args.target_report,
        "requested_agents": args.agents,
        "run_dir": str(run_dir),
        "slurm_command": build_slurm_command(args),
        "apptainer_command": build_apptainer_command(args, run_dir),
        "agent_command": agent_command,
        "agent_command_candidates": list(adapter.command_candidates),
        "config_mount": f"{ROOT}:/home/sandbox/ai-agent-config:ro",
        "auth_mounts": [
            {
                "host_path": str(auth.host_path),
                "container_path": auth.container_path,
                "writable": auth.writable,
                "exists": auth.host_path.exists(),
            }
            for auth in adapter.auth_paths
        ],
    }
    print(json.dumps(capsule, indent=2, ensure_ascii=False))
    if getattr(args, "show_mounts", False):
        print("\n--- mounts ---")
        for item in build_apptainer_command(args, run_dir):
            if ":" in item and ("/workspace" in item or "/runs" in item or "/scratch" in item or "/cache" in item or "/home/sandbox" in item):
                print(item)
    print("\n--- prompt.txt ---")
    print(prompt, end="")
    return 0


def write_run_plan(args: argparse.Namespace, run_dir: Path, prompt: str, capsule: dict[str, object]) -> None:
    make_run_layout(run_dir)
    write_latest(run_dir)
    prepare_run_home(run_dir)
    profile = get_profile(args.mode)
    time_limit = args.time or profile.time

    (run_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    (run_dir / "capsule.yaml").write_text(
        "\n".join(
            [
                f"run_id: {capsule['run_id']}",
                f"mode: {capsule['mode']}",
                f"agent: {capsule['agent']}",
                f"repo: {capsule['repo']}",
                f"goal: {capsule['goal'] or ''}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    if args.goal:
        goal_text = Path(args.goal).read_text(encoding="utf-8")
    else:
        goal_text = f"mode: {args.mode}\nagent: {args.agent}\n"
    (run_dir / "goal.yaml").write_text(goal_text, encoding="utf-8")

    apptainer_command = shlex.join(capsule["apptainer_command"])
    apptainer_script = run_dir / "apptainer_exec.sh"
    submit_script = run_dir / "submit.sbatch"
    apptainer_script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"{apptainer_command}\n",
        encoding="utf-8",
    )
    submit_script.write_text(
        "#!/usr/bin/env bash\n"
        f"#SBATCH --job-name=agentrun-{args.mode}-{args.agent}\n"
        f"#SBATCH --partition={'large-david02' if args.gpus else 'small-david02'}\n"
        f"#SBATCH --time={time_limit}\n"
        f"#SBATCH --mem={'64000M' if args.mode == 'experiment' else '32000M'}\n"
        f"#SBATCH --cpus-per-task={'8' if args.mode == 'experiment' else '4'}\n"
        + (f"#SBATCH --gres=gpu:{args.gpus}\n" if args.gpus else "")
        + f"#SBATCH --output={run_dir}/live/slurm.out\n"
        + f"#SBATCH --error={run_dir}/live/slurm.err\n\n"
        + "set -euo pipefail\n"
        + f"printf '%s\\n' \"${{SLURM_JOB_ID:-}}\" > {run_dir}/live/slurm_job_id.txt\n"
        + f"env | sort > {run_dir}/artifacts/environment.txt\n"
        + f"apptainer --version > {run_dir}/artifacts/container.txt 2>/dev/null || true\n"
        + "set +e\n"
        + f"bash {run_dir}/apptainer_exec.sh\n"
        + "rc=$?\n"
        + "set -e\n"
        + f"printf '%s\\n' \"$rc\" > {run_dir}/live/exit_code.txt\n"
        + "exit \"$rc\"\n",
        encoding="utf-8",
    )
    os.chmod(apptainer_script, 0o755)
    os.chmod(submit_script, 0o755)


def prepare_run_home(run_dir: Path) -> None:
    for rel in [".claude", ".codex", ".agents", ".gemini", ".antigravity"]:
        (run_dir / "home" / rel).mkdir(parents=True, exist_ok=True)


def command_prepare_run(args: argparse.Namespace) -> int:
    agent = args.agent or DEFAULT_AGENT
    adapter = get_adapter(agent)
    run_id = build_run_id(args.mode, agent)
    run_dir = Path.cwd() / ".agent-runs" / run_id
    prompt = build_prompt(args, agent, args.prompt)
    agent_command = adapter.build_command("/runs/prompt.txt", args.mode)
    capsule = {
        "run_id": run_id,
        "mode": args.mode,
        "agent": agent,
        "repo": args.repo,
        "goal": args.goal,
        "run_dir": str(run_dir),
        "slurm_command": build_slurm_command(args),
        "apptainer_command": build_apptainer_command(args, run_dir),
        "agent_command": agent_command,
    }
    write_run_plan(args, run_dir, prompt, capsule)
    print(f"prepared run: {run_dir}")
    print(f"submit script: {run_dir / 'submit.sbatch'}")
    if args.submit:
        return subprocess.call(["sbatch", str(run_dir / "submit.sbatch")])
    return 0


def make_run_layout(run_dir: Path) -> None:
    for rel in ["live", "artifacts", "reviews", "workspace", "scratch", "cache", "home"]:
        (run_dir / rel).mkdir(parents=True, exist_ok=True)


def write_latest(run_dir: Path) -> None:
    latest = run_dir.parent / "latest"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(run_dir.name)


def command_smoke_test(args: argparse.Namespace) -> int:
    agent = args.agent or DEFAULT_AGENT
    if agent not in AGENTS:
        raise SystemExit(f"unknown agent: {agent}")

    run_id = build_run_id("smoke-test", agent)
    run_dir = Path.cwd() / ".agent-runs" / run_id
    make_run_layout(run_dir)
    write_latest(run_dir)

    status = {
        "status": "success",
        "agent": agent,
        "mode": "smoke-test",
        "updated_at": utc_now(),
        "note": "Deterministic local smoke-test; no agent, Slurm, or Apptainer process was started.",
    }
    (run_dir / "live" / "status.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    (run_dir / "live" / "heartbeat.txt").write_text(utc_now() + "\n", encoding="utf-8")
    (run_dir / "live" / "stdout.log").write_text("smoke-test stdout\n", encoding="utf-8")
    (run_dir / "live" / "stderr.log").write_text("", encoding="utf-8")
    (run_dir / "live" / "current_task.md").write_text("Smoke test completed.\n", encoding="utf-8")
    event = {"ts": utc_now(), "event": "smoke-test", "agent": agent, "status": "success"}
    (run_dir / "live" / "command_log.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")

    (run_dir / "artifacts" / "report.md").write_text("# Smoke Test Report\n\nPassed.\n", encoding="utf-8")
    (run_dir / "artifacts" / "git_diff.patch").write_text("", encoding="utf-8")
    metrics = {"smoke_test": True, "status": "passed", "agent": agent}
    (run_dir / "artifacts" / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    (run_dir / "capsule.yaml").write_text(f"run_id: {run_id}\nagent: {agent}\nmode: smoke-test\n", encoding="utf-8")
    (run_dir / "prompt.txt").write_text("Local smoke-test prompt.\n", encoding="utf-8")
    (run_dir / "goal.yaml").write_text("mode: smoke-test\n", encoding="utf-8")

    print(run_dir)
    return 0


def resolve_run_dir(value: str) -> Path:
    path = Path(value)
    if path.is_symlink():
        path = path.resolve()
    return path


def validate_json_file(path: Path) -> tuple[bool, str]:
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, str(exc)
    return True, ""


def validate_jsonl_file(path: Path) -> tuple[bool, str]:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                json.loads(line)
    except Exception as exc:
        return False, str(exc)
    return True, ""


def command_verify_run(args: argparse.Namespace) -> int:
    if args.run_id:
        run_dir = Path.cwd() / ".agent-runs" / args.run_id
    elif args.run_dir:
        run_dir = resolve_run_dir(args.run_dir)
    else:
        run_dir = resolve_run_dir(str(Path.cwd() / ".agent-runs" / "latest"))
    required = list(REQUIRED_OUTPUTS)
    checks = [Check(str(run_dir), run_dir.exists(), "run directory")]
    for rel in required:
        path = run_dir / rel
        checks.append(Check(rel, path.exists(), "exists"))

    report = run_dir / "artifacts" / "report.md"
    checks.append(Check("artifacts/report.md nonempty", report.exists() and bool(report.read_text(encoding="utf-8").strip())))

    mode = ""
    capsule = run_dir / "capsule.yaml"
    if capsule.exists():
        for line in capsule.read_text(encoding="utf-8").splitlines():
            if line.startswith("mode:"):
                mode = line.split(":", 1)[1].strip()
                break
    profile_required = PROFILE_REQUIRED_OUTPUTS.get(mode)
    if profile_required is None:
        checks.append(Check("profile required outputs", False, f"unknown mode: {mode or 'missing'}"))
    else:
        for rel in profile_required:
            checks.append(Check(f"profile_required:{rel}", (run_dir / rel).exists(), "exists"))

    for rel in ["live/status.json", "artifacts/metrics.json"]:
        path = run_dir / rel
        if path.exists():
            ok, detail = validate_json_file(path)
            checks.append(Check(f"{rel} parse", ok, detail))

    log = run_dir / "live" / "command_log.jsonl"
    if log.exists():
        ok, detail = validate_jsonl_file(log)
        checks.append(Check("live/command_log.jsonl parse", ok, detail))

    status_path = run_dir / "live" / "status.json"
    if status_path.exists():
        try:
            status = json.loads(status_path.read_text(encoding="utf-8")).get("status", "")
        except Exception as exc:
            checks.append(Check("final_status", False, str(exc)))
        else:
            checks.append(Check("final_status", status in {"success", "failed", "cancelled", "timeout"}, status or "missing"))

    checks.append(Check("live/exit_code.txt", (run_dir / "live" / "exit_code.txt").exists(), "exists"))
    checks.append(Check("live/slurm_job_id.txt", (run_dir / "live" / "slurm_job_id.txt").exists(), "exists"))

    return print_checks(checks)


def command_status(args: argparse.Namespace) -> int:
    path = Path.cwd() / ".agent-runs" / "latest" / "live" / "status.json"
    if not path.exists():
        print(f"status not found: {path}", file=sys.stderr)
        return 1
    print(path.read_text(encoding="utf-8"), end="")
    return 0


def command_logs(args: argparse.Namespace) -> int:
    path = Path.cwd() / ".agent-runs" / "latest" / "live" / "stdout.log"
    if not path.exists():
        print(f"log not found: {path}", file=sys.stderr)
        return 1
    if args.follow:
        return subprocess.call(["tail", "-f", str(path)])
    print(path.read_text(encoding="utf-8"), end="")
    return 0


def command_list_runs(args: argparse.Namespace) -> int:
    root = Path.cwd() / ".agent-runs"
    if not root.exists():
        return 0
    for path in sorted(root.iterdir()):
        if path.name != "latest":
            print(path.name)
    return 0


def command_open_run(args: argparse.Namespace) -> int:
    target = args.run_dir or str(Path.cwd() / ".agent-runs" / "latest")
    print(resolve_run_dir(target))
    return 0


def add_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("mode", choices=sorted(PROFILES))
    parser.add_argument("prompt")
    parser.add_argument("--agent", choices=sorted(AGENTS), default=DEFAULT_AGENT)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--goal")
    parser.add_argument("--gpus", type=int, default=0)
    parser.add_argument("--time")
    parser.add_argument("--show-mounts", action="store_true")
    parser.add_argument("--reviewers")
    parser.add_argument("--target-diff")
    parser.add_argument("--target-report")
    parser.add_argument("--agents")
    parser.add_argument("--submit", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentrun")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate")
    validate.set_defaults(func=command_validate)

    doctor = sub.add_parser("doctor")
    doctor.add_argument("--agent", choices=sorted(AGENTS), default=DEFAULT_AGENT)
    doctor.add_argument("--all", action="store_true")
    doctor.set_defaults(func=command_doctor)

    agents = sub.add_parser("agents")
    agents.set_defaults(func=command_agents)

    dry_run = sub.add_parser("dry-run")
    add_run_args(dry_run)
    dry_run.set_defaults(func=command_dry_run)

    for mode in sorted(PROFILES):
        run_mode = sub.add_parser(mode)
        run_mode.add_argument("prompt")
        run_mode.add_argument("--agent", choices=sorted(AGENTS), default=DEFAULT_AGENT)
        run_mode.add_argument("--repo", default=".")
        run_mode.add_argument("--goal")
        run_mode.add_argument("--gpus", type=int, default=0)
        run_mode.add_argument("--time")
        run_mode.add_argument("--show-mounts", action="store_true")
        run_mode.add_argument("--reviewers")
        run_mode.add_argument("--target-diff")
        run_mode.add_argument("--target-report")
        run_mode.add_argument("--agents")
        run_mode.add_argument("--submit", action="store_true")
        run_mode.set_defaults(func=command_prepare_run, mode=mode)

    smoke = sub.add_parser("smoke-test")
    smoke.add_argument("--agent", choices=sorted(AGENTS), default=DEFAULT_AGENT)
    smoke.set_defaults(func=command_smoke_test)

    verify = sub.add_parser("verify-run")
    verify.add_argument("run_dir", nargs="?")
    verify.add_argument("--run-id")
    verify.set_defaults(func=command_verify_run)

    status = sub.add_parser("status")
    status.set_defaults(func=command_status)

    logs = sub.add_parser("logs")
    logs.add_argument("--follow", action="store_true")
    logs.set_defaults(func=command_logs)

    tail = sub.add_parser("tail")
    tail.set_defaults(func=command_logs, follow=True)

    runs = sub.add_parser("list-runs")
    runs.set_defaults(func=command_list_runs)

    open_run = sub.add_parser("open-run")
    open_run.add_argument("run_dir", nargs="?")
    open_run.set_defaults(func=command_open_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
