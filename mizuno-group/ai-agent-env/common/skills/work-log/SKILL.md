---
name: work-log
description: >
  Record implementation progress in agents-work-log/YYYY-MM-DD.md.
  Use at meaningful checkpoints: task starts, completions, errors, and key decisions.
---

# work-log

Append a dated entry to `agents-work-log/YYYY-MM-DD.md` (relative to the working
directory, e.g. `/workspace/agents-work-log/` inside a container).

## When to log

- Starting a new task or subtask
- Completing a meaningful step
- Encountering an unexpected error or behavior
- Resolving a problem — record the cause and fix
- Finishing a session

## Entry format

```markdown
## HH:MM — <one-line summary>

**What**: <what was done or attempted>
**Observed**: <any unexpected behavior or error>
**Resolution**: <how it was resolved, if applicable>
**Files changed**: <list of modified files, if any>
```

## Rules

- Append only; never rewrite existing entries.
- Use local time (or UTC if local is unavailable) for headings.
- Record facts: file paths, error messages, commands run. Avoid vague summaries.
- One entry per checkpoint, not per tool call.
