# BASE GUIDELINES
Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

# CODING STANDARDS
- Unless otherwise instructed by the user, all code comments, docstrings, and documentation must be written in English.
- Implement code in a strict, fail-fast manner: validate assumptions explicitly, raise clear errors on unexpected inputs or states, and minimize silent or implicit fallback behavior.

# DEVELOPMENT WORKFLOW
- Assume that the current machine is a SLURM cluster login node. DO NOT run GPU workloads or code that depends on non-standard/non-built-in libraries directly on the login node, except for trivial sanity checks. Use `srun` or `sbatch` for such executions.
- Before invoking `srun` or `sbatch`, consult the `CLAUDE.md` file in the working directory and follow the specified arguments, including the appropriate partition.

## Python Environment Rules
- Python environments are managed with uv. Venvs live as `.venv*`-style directories in the project root. There is NO default Python on either the login node or compute nodes.
- Before generating any `srun`/`sbatch` command that invokes Python, you MUST confirm which venv to use. Check the session env file: `/tmp/claude_python_env_<md5 of cwd, first 8 chars>`. If not set, run `find . -maxdepth 5 -name activate -path "*/bin/activate"` to list candidates and ask the user to choose. Write the chosen path with `echo '<path>' > <session_env_file>`.
- **srun (debug/quick check):** `srun <options> bash -c "source <venv>/bin/activate && python ..."`
- **sbatch (production):** include `source <venv>/bin/activate` in the job script before any python call.
