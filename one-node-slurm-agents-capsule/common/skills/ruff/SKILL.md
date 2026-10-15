---
name: ruff
description:
  Guide for using ruff, the fast Python linter and formatter. Use this when
  linting or formatting Python files after editing them.
---

# ruff

ruff is an extremely fast Python linter and formatter written in Rust. It replaces
flake8, isort, black, and others.

## Important: no auto-formatter in this capsule

The `post_edit_format.py` hook records that an edit happened but does **not** run
any formatter automatically. You must run ruff yourself after editing Python files.

## Running ruff

Use `uvx` to run ruff without installing it:

```bash
uvx ruff check path/to/file.py        # lint a file
uvx ruff check src/                   # lint a directory
uvx ruff check --fix src/             # lint and auto-fix safe issues
uvx ruff format path/to/file.py       # format a file
uvx ruff format src/                  # format a directory
```

Or if ruff is already a project dependency:

```bash
uv run ruff check src/
uv run ruff format src/
```

## Typical post-edit workflow

After editing one or more Python files:

```bash
uvx ruff check --fix path/to/edited_file.py
uvx ruff format path/to/edited_file.py
```

## Check vs format

| command | what it does |
| ------- | ------------ |
| `ruff check` | lint: finds style and correctness issues |
| `ruff check --fix` | lint and apply safe automatic fixes |
| `ruff format` | reformat code (like black) |

Run `check` before `format`. Fix lint errors first, then format.

## Configuration

ruff reads `pyproject.toml` or `ruff.toml` if present in the project. If no
config exists, ruff uses its defaults (similar to black + flake8 E/W rules).

```toml
# pyproject.toml example
[tool.ruff]
line-length = 100

[tool.ruff.lint]
select = ["E", "W", "F", "I"]
```

## Common issues

```bash
# F401 unused import — remove the import or add `# noqa: F401`
# E501 line too long — ruff format handles this automatically
# I001 import order — ruff check --fix fixes this
```
