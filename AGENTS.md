# Quack Norris — Agent Guidelines

Follow these conventions when working in this codebase.

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
