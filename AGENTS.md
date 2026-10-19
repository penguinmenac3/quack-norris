# Quack Norris — Agent Guidelines

Follow these conventions when working in this codebase.

---

## Development Workflow

Use the Microfactory workflow for all development; never jump directly to implementation. Use the `mf-plan` skill to plan work first, then use the `autonomous-coding` skill to implement only after a plan/task breakdown exists. Before starting, verify that `mf` and both skills are available. If Microfactory or either skill is missing, ask the user to install Microfactory and run `mf skills install microfactory`, then continue.

---

## Running Tests

Use `uv run python -m pytest` from the project root:

```bash
# Run all tests (excluding live tests)
uv run python -m pytest

# Run including live tests (require a running Ollama instance)
uv run python -m pytest -m live

# Run a specific test file
uv run python -m pytest tests/test_approver.py
```

Live tests (marked `@pytest.mark.live`) call a real LLM (`ollama/granite4:tiny-h`) and may be flaky depending on model behavior.
