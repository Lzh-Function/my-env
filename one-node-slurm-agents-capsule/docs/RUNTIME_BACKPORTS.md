# Runtime fixes backported from agent-capsule

Reviewed the local `agent-capsule` history through `7778a21` on 2026-10-20 and
compared its runtime with `my-env` at `9d653ee`. Changes are adapted to the
existing `one-node-slurm-agents-capsule/` layout rather than merging the upstream tree.

| Source commit | Adopted fixes |
| --- | --- |
| `fa0d8e7` | Restore batch repository locking and quote smoke-test paths using the existing Slurm log directive helper. |
| `751baef` | Record selected reproducibility environment fields instead of credentials; prevent inherited implicit mounts and GitHub token injection; stop before agent startup if its enabled GitHub broker fails. |
| `eb91676` | Remove an obsolete `base-agent.sif` only after a successful forced system-image build. |
| `384dd38` | Explicitly request one node and one task for batch, interactive, and resumed runs, overriding inherited allocation counts. |
| `e626ed5` | Bind compute-node DNS files for agents and the existing GitHub broker; report installer DNS failures. |
| `1ef5a1b` | Bound installer, broker, terminal, finalizer, and process shutdown waits; keep the repository lock out of child processes; stop hung local `srun` after confirmed Slurm completion; cache shared history scans per listing. |
| `8979a86`, `0402ffa` | Download the Codex installer archive into its existing cache-backed temporary HOME instead of the container's small `/tmp`. The target did not contain conflict markers. |
| `dec534d` | Allocate distinct run directories atomically; normalize broker signal exit codes; fix zero-sized PTY fixtures in wizard tests. |
| `7778a21` | Keep Codex runtime helpers off NFS in container-local `/tmp`; retry transient HOME deletion failures and preserve diagnostics. |

The existing agent selection/default, profiles, native agent settings, hooks,
shared skills, host-side authentication/staging, auth store locations, and
single-image build architecture are retained. Codex and Claude Code remain the
only supported agents, with Claude Code as the default. The shared skills, Rust
and TeX image contents, centralized history directory/database, `launcher_cwd`
metadata, and host-only conversation export are retained. Added process helpers are internal
to the current launcher, with no new service or broker.

Excluded changes:

- Policy unification, managed native configuration, hook trust, and the new Slurm
  submission broker (`751baef`, `6ce1b14`, `37d2673`). Applying these would require
  changing the existing policy/configuration architecture. Native `--strict-config`
  flags that depend on that migration are not introduced by this backport.
- Authentication inside the container, shared user-state relocation, and config
  snapshot/direct-bind redesign (`e0fd1f2`, `384dd38`, `ad13c0a`, `2ed36e9`). Only
  the independently applicable one-node/one-task fix from `384dd38` is adopted.
  The target already binds its shared configs directly and has no `cp -a` snapshot.
- New partition support, notification services, Docker Slurm topology, and CI
  namespace setup. These are features or infrastructure changes, not runtime
  corrections needed for this port.
- Statusline executable-bit fix `e8d0191`: already present in the target.

Regression coverage uses synthetic installers, GitHub commands, Slurm queries,
PTYs, transient busy files, and generated batch scripts. Local tests do not
submit real jobs, download agent CLIs, or require an image rebuild.

For this launcher, interactive conversation export still runs on the launch host
before HOME deletion and has a 120-second cleanup deadline. Timeout failures are
recorded for manual retry with `agentrun history`. Batch HOME cleanup stays on the
compute node, including its completion marker; its detached history collector
stays on the submission host. Batch submission explicitly overrides inherited
node/task counts, and queue display filters cannot hide an active job from the
host collector. Existing archive/resume/default-agent tests remain in the suite.
