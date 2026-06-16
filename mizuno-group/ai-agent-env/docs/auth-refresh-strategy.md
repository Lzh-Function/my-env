# Auth Refresh Strategy

This document records the current implementation philosophy for agent authentication in
`agentrun`, and the recommended direction for OAuth token refresh handling.

The intended runtime model of this repository is:

```text
Slurm compute node
  -> Apptainer sandbox
  -> disposable per-run home
  -> agent CLI
```

Direct host use of Claude Code, Codex, or Antigravity is not the primary product surface.
The host login node is used to prepare and submit jobs, not to run agent workloads.

## Core Principles

### 1. The repository is the config source of truth

The `ai-agent-env` repository is mounted into the container as:

```text
<repo>/mizuno-group/ai-agent-env -> /home/sandbox/ai-agent-config:ro
```

This repository owns:

- shared instructions
- common hooks
- common skills
- agent-specific config templates
- generated hook manifests
- `agentrun` itself

It must not own live credentials, OAuth tokens, user sessions, cache, or model history.

### 2. Runtime home is disposable

Each run gets a private home directory:

```text
<run_dir>/home -> /home/sandbox
```

This home exists only for the lifetime of the run. It is writable inside the container so
agent CLIs can create trust files, config state, cache, and token refresh state without
writing into the Git-managed config repository.

After submitted jobs finish, `<run_dir>/home` is removed by the generated cleanup trap.
This is intentional: run-local home content is treated as ephemeral unless explicitly
promoted by `agentrun`.

### 3. Host `$HOME` is not mounted wholesale

The implementation must not mount the host home directory into the container. It should
also avoid mounting full agent home directories such as `$HOME/.claude`, `$HOME/.codex`,
or `$HOME/.gemini` as read/write state.

Reasons:

- host home contains unrelated secrets and personal state
- multiple Slurm jobs can race on the same files
- failed or compromised runs could corrupt host credentials
- CLI token refresh often rewrites files, sometimes via atomic rename
- file-level bind mounts can behave poorly with rename-based updates
- this project wants sandboxed compute-node execution, not host-direct agent operation

### 4. Auth is runtime state, not config

Authentication files are operational state. They are staged into the run home only when
needed.

Current staged files are:

```text
claude:
  $HOME/.claude/.credentials.json
  $HOME/.claude.json

codex:
  $HOME/.codex/auth.json

antigravity:
  $HOME/.gemini/antigravity-cli/antigravity-oauth-token
  $HOME/.gemini/antigravity-cli/installation_id
```

The container sees these files through `/home/sandbox`, not through direct host mounts.

## Current Implementation

At launch time, `agentrun` currently copies host-side auth files into the run home:

```text
host auth files
  -> <run_dir>/home/...
  -> /home/sandbox/...
```

The generated run then starts the selected agent under `/workspace`:

```text
<repo selected by --repo or current directory> -> /workspace:rw
```

Config and shared assets are mounted or linked separately from auth:

```text
ai-agent-env repository -> /home/sandbox/ai-agent-config:ro
common hooks            -> agent-specific hook path, or referenced through requirements
common skills           -> agent-specific skill path
agent config            -> read-only mount or writable run-home copy, depending on CLI needs
```

Codex is special because its TUI needs to persist trust/config state. Its selected
`config.toml` is copied into:

```text
<run_dir>/home/.codex/config.toml
```

This avoids read-only config persistence failures while keeping the Git-managed config
template immutable.

## Current Auth Refresh Detection

The current implementation detects, but does not resolve, auth refreshes.

After auth files are copied into the run home, `agentrun` records hashes in:

```text
<run_dir>/artifacts/auth_baseline.tsv
```

At job cleanup time, it compares:

- host auth hash at staging time
- host auth hash at cleanup time
- run-home auth hash at staging time
- run-home auth hash at cleanup time

The results are written to:

```text
<run_dir>/live/auth_refresh_detected.txt
<run_dir>/artifacts/auth_refresh_report.tsv
```

If a run-home auth file changed, the report may indicate an OAuth token refresh. However,
the refreshed file is not copied back to the host.

This is deliberate. Automatic copy-back to the original host auth file would make failed
runs and concurrent jobs capable of mutating the user's real credentials.

## Known Gap

The current implementation can lose a successful token refresh:

```text
host auth
  -> copied into run home
  -> agent refreshes token inside run home
  -> job exits
  -> run home is removed
  -> refreshed token is lost
```

This can lead to repeated authentication failures if the original host-side token is stale.

The existing detector makes this visible, but it is not yet a persistence mechanism.

## Recommended Direction

The preferred next step is an `agentrun`-managed persistent auth store:

```text
$HOME/.agentrun/auth/<agent>/...
```

This store should become the `agentrun` source of truth after initial import.

Recommended flow:

```text
initial host auth
  -> agentrun auth import
  -> $HOME/.agentrun/auth/<agent>/...
  -> copied into <run_dir>/home at launch
  -> agent may refresh inside run home
  -> successful refresh is promoted back to $HOME/.agentrun/auth/<agent>/...
```

The original host agent homes should not be treated as the long-term mutable source of
truth for Slurm capsule runs.

## Promotion Rules

Promotion from run home back to the persistent auth store should be conservative.

Recommended default rules:

```text
if job exit code is 0
  and run-home auth file changed
  and auth store has not changed since launch
then
  promote refreshed auth into $HOME/.agentrun/auth/<agent>/...
else
  do not overwrite the auth store
```

For failed jobs:

```text
do not promote by default
keep the detection report
optionally preserve the refreshed file in an explicit conflict/debug location
```

For concurrent jobs:

```text
use a per-agent auth lock
compare the auth-store baseline before writing
if the store changed during the run, report a conflict instead of overwriting
```

For conflicts:

```text
write a clear report
preserve the candidate refreshed file under $HOME/.agentrun/auth-conflicts/<run_id>/...
require manual resolution
```

## Suggested Commands

Keep the user-facing surface small.

```bash
agentrun auth import --agent codex
agentrun auth import --all
agentrun auth status --all
agentrun auth reset --agent codex
```

Possible later additions:

```bash
agentrun auth conflicts --all
agentrun auth promote --run-id <run_id>
```

These later commands should only be added if real conflict handling needs them.

## Why Not Direct Read/Write Mounts

A direct read/write mount such as:

```text
$HOME/.codex/auth.json -> /home/sandbox/.codex/auth.json:rw
```

or:

```text
$HOME/.claude -> /home/sandbox/.claude:rw
```

is simpler, but it weakens the isolation model.

It allows every running job to mutate the real host credential files. It also makes
concurrent refreshes hard to reason about, and it can fail subtly when CLIs update files
by writing a temporary file and renaming it over the original.

The safer model is:

```text
copy in
run in disposable home
detect changes
promote only under explicit rules
```

## Agent-Specific Notes

### Claude

Claude currently stages:

```text
.claude/.credentials.json
.claude.json
```

Claude may update both files during authentication failure, recovery, or token refresh.
Promotion should treat them as a small file set for the same agent, not as unrelated
independent files.

### Codex

Codex currently stages:

```text
.codex/auth.json
```

Codex config is separate from auth. The writable run-home `config.toml` exists so Codex
can persist trust/config updates without writing to read-only repository config.

Do not promote `config.toml` as auth.

### Antigravity

Antigravity currently stages:

```text
.gemini/antigravity-cli/antigravity-oauth-token
.gemini/antigravity-cli/installation_id
```

The token and installation ID should be copied and promoted as part of the same agent auth
state. Agent settings are config, not auth.

## Implementation Boundary

Auth refresh handling should stay inside `agentrun`. Individual agent configs should not
grow separate copy-back logic.

The shared implementation should provide:

- auth file inventory per agent
- import from host agent homes
- staging from persistent auth store to run home
- hash baselines
- cleanup-time detection
- conservative promotion
- conflict reporting

Agent-specific code should only describe which files belong to that agent's auth state.

## Status

Current state (implemented):

- `$HOME/.agentrun/auth/<agent>/...` is the persistent auth store
- `agentrun auth import --all` populates the store from host agent homes
- `agentrun auth status [--agent NAME]` shows store and host presence per file
- `agentrun auth reset --agent NAME` removes an agent's store directory
- `agentrun auth conflicts` lists saved conflict files
- auth files are staged from store (store-first, host fallback) into run home at launch
- run home is removed after submitted jobs
- auth refresh detection and hash baseline exist (`artifacts/auth_baseline.tsv`)
- successful, non-conflicting runs auto-promote refreshed tokens to store (`AUTH_REFRESH_PROMOTED`)
- failed or conflicting runs save refreshed tokens to `$HOME/.agentrun/auth-conflicts/<run_id>/` (`AUTH_REFRESH_CONFLICT`)
- host agent homes are no longer in the normal run-time mutation path
