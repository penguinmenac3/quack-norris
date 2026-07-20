# Quack Norris — Agent Guidelines

Follow these conventions when working in this codebase.

---

## CLI Status Tracking

**`CLI_STATUS.md` is the source of truth for what is and isn't implemented in the CLI.**

- When you implement a new feature, fix a gap, or complete something listed under **Not yet implemented**, update `CLI_STATUS.md` accordingly.
- Move completed items into the **Implemented** section with a concise description matching the style of existing entries (one bullet, dense, factual).
- When you add a genuinely new capability that wasn't previously tracked, add it to **Implemented**.
- Do not remove or reword existing entries without good reason — the history of what was built and how it works is intentional.

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
