# TODO

Deferred follow-up work. These items are intentionally not part of the current implementation session.

## Generated session titles

Current behavior:

- The first non-command prompt, normalized and truncated to 80 characters, becomes the title.
- `SessionInfoUpdate`, `session/list`, and `session/load` work correctly, but the value is a prompt excerpt rather than a real title.

Desired behavior:

- Generate a short descriptive title from the first user turn, optionally including the first assistant result.
- Keep title generation independent from the main conversation history.
- Prefer a small/cheap configured model where available.
- Strip quotes, markdown, and trailing punctuation from model output.
- Use a deterministic prompt excerpt as fallback when generation fails.
- Persist and emit the generated title through the existing ACP flow.

Done when:

- New sessions receive a concise human-readable title rather than the first message verbatim.
- Title generation failure does not fail or delay the main turn significantly.
- Listed and loaded sessions retain the generated title.
- Tests cover successful generation, cleanup, fallback, persistence, and ACP update ordering.

## Approval options and whitelist scopes

Current behavior:

- Permission requests offer only allow once and reject once.
- Previous project/global command whitelist workflows are not available through ACP mode.

Desired behavior to investigate:

- Allow once.
- Allow and remember safe command variants for the current project.
- Allow and remember safe command variants globally.
- Reject once.
- Consider reject always where useful.

Questions:

- ACP provides `allow_once`, `allow_always`, `reject_once`, and `reject_always`, but no project/global scope. Decide which state belongs to the ACP client and which belongs to Quack Norris.
- Define safe, understandable command variants without creating overly broad shell patterns.
- Decide where project and global rules are stored after removal of the old CLI whitelist package.
- Ensure remembered approvals cannot bypass workspace/path validation.
- Verify why reject is not visible in the tested client despite a reject option being sent.

Done when:

- The client displays all intended choices.
- Session/project/global persistence semantics are explicit.
- Matching and precedence are covered by security-focused tests.

## Fast terminal completion before deferring

Current behavior:

- Every terminal command returns an operation handle.
- Even immediately completed commands require `await_tool`.

Desired behavior:

1. Start the ACP terminal.
2. Wait or poll for a short configurable threshold.
3. If the command finishes within the threshold, return its output and exit status directly and release the terminal.
4. Only register and return an operation handle when it is still running after the threshold.

Requirements:

- Preserve stdout, truncation state, and non-zero exit handling.
- Release fast-completed terminals exactly once.
- Keep cancellation safe during the threshold window.
- Do not lose output between the initial wait/poll and deferred operation registration.
- Use one threshold for native and ACP terminal backends where practical.
- Add tests for instant success, instant failure, threshold boundary, deferred completion, cancellation, and release cleanup.
