---
name: pytest
description:
  Guide for running pytest inside an agentrun capsule. Use this when running
  tests, checking test results, or writing test output to the run ledger.
---

# pytest inside an agentrun capsule

## Running tests

System Python is reserved for capsule infrastructure. Run project tests through `uv`:

```bash
# Run all tests
uv run pytest

# Run a specific file
uv run pytest tests/test_model.py

# Run a specific test
uv run pytest tests/test_model.py::test_forward_pass

# Run with verbosity
uv run pytest -v

# Stop on first failure
uv run pytest -x

# Show local variables on failure
uv run pytest -l
```

If the project has no `pyproject.toml` with pytest config, add `-p no:cacheprovider`
to avoid writing `.pytest_cache` to `/workspace` unnecessarily:

```bash
uv run pytest -p no:cacheprovider
```

## Logging test results to /runs

Write a summary to the run ledger so the operator can see results without reading
raw pytest output:

```bash
uv run pytest --tb=short -q 2>&1 | tee /runs/live/stdout.log
```

Or capture exit code and record it:

```bash
set +e
uv run pytest -v --tb=short > /tmp/pytest_output.txt 2>&1
pytest_rc=$?
set -e
cat /tmp/pytest_output.txt | tee -a /runs/live/stdout.log

# Record in metrics
passed=$(grep -c "PASSED" /tmp/pytest_output.txt || true)
failed=$(grep -c "FAILED" /tmp/pytest_output.txt || true)
printf '{"tests_passed":%s,"tests_failed":%s,"pytest_exit_code":%s}\n' \
    "$passed" "$failed" "$pytest_rc" > /runs/artifacts/metrics.json
```

## Common patterns

### Checking if tests pass before committing

```bash
uv run pytest -x -q || { echo "Tests failed; not committing."; exit 1; }
git add -p
git commit -m "..."
```

### Running tests with coverage

```bash
uv run pytest --cov=src --cov-report=term-missing
```

### Skipping slow tests

```bash
uv run pytest -m "not slow"
```

## Fixtures and conftest

If the project uses conftest.py for fixtures, `uv run pytest` picks it up
automatically. No extra setup is needed.

## If pytest is not installed

```bash
# Check if available
uv run python -c "import pytest" 2>/dev/null && echo "available" || echo "not installed"

# Add it temporarily for the run (does not modify pyproject.toml)
uv run --with pytest pytest
```
