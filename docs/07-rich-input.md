# Rich User Input — Spec

Multi-line entry, bulk paste detection, and image input for the interactive REPL.

---

## 1. Goals

| # | Goal |
|---|---|
| G1 | Single `Enter` submits, as today — no behaviour change for the common case |
| G2 | `\` at the end of a line continues input onto the next line (explicit continuation) |
| G3 | Bulk pastes (≥ 2 lines arriving faster than a threshold) are captured as a single message, shown as `[pasted N lines]` in the prompt echo, but sent to the LLM verbatim |
| G4 | An image pasted / drag-dropped into the terminal is captured as a single message shown as `[pasted image: <filename or dimensions>]`, sent to the LLM as a vision content part |
| G5 | No new required dependencies — `select`/`msvcrt` for paste detection on Windows/POSIX; `base64` is stdlib |

---

## 2. Multi-line Continuation (`\` + Enter)

### 2.1 UX

```
> Tell me about \
... Python decorators \
... and when to use them
```

- First line: `> ` prompt, user types text ending in `\` and hits Enter.
- Subsequent lines: `... ` continuation prompt until a line does **not** end in `\`.
- The trailing `\` characters are stripped; lines are joined with `\n`.
- An empty continuation line (just Enter after `\`) is legal — it inserts a blank line.

### 2.2 Implementation — `_prompt_sync()` in `cli/__main__.py`

```python
def _prompt_sync() -> str:
    lines: list[str] = []
    prompt = "> "
    while True:
        line = input(prompt)
        if line.endswith("\\"):
            lines.append(line[:-1])   # strip the backslash
            prompt = "... "
        else:
            lines.append(line)
            break
    return "\n".join(lines)
```

No other callers change. `_read_input()` already wraps this in `run_in_executor`.

---

## 3. Bulk Paste Detection

### 3.1 The Problem

`input()` submits on the first `\n` in a paste. A 12-line paste produces 12
sequential `input()` calls — the first fires immediately, the rest appear as
separate messages on the next REPL iterations.

### 3.2 Detection Strategy

Replace the blocking `input()` call in `_prompt_sync()` with a character-by-character
reader that checks whether more data arrives within a short window
(`PASTE_WINDOW_MS`, default **20 ms**) after the first newline.

```
read chars until \n
  → if more data arrives within PASTE_WINDOW_MS:
        switch to "paste drain" mode — keep reading until PASTE_WINDOW_MS of silence
  → else: single-line path (existing behaviour)
```

Cross-platform character readers:

| Platform | API |
|---|---|
| Windows | `msvcrt.getwch()` in a tight loop with `time.perf_counter()` |
| POSIX | `sys.stdin` set to non-blocking via `select.select(timeout=PASTE_WINDOW_MS/1000)` |

### 3.3 The Abstraction — `cli/input.py` (new file)

All input logic moves to a new module so `__main__.py` stays clean.

```python
# cli/input.py

PASTE_WINDOW_MS: int = 20   # configurable via env QUACK_PASTE_WINDOW_MS

def read_user_input() -> "UserInput":
    """Blocking call. Returns a UserInput describing what the user entered."""
    ...
```

`UserInput` is a small dataclass:

```python
@dataclass
class UserInput:
    kind: Literal["text", "paste", "image"]
    text: str                        # always set; for "image" this is the display label
    raw_lines: list[str]             # original lines before joining
    image_data: "ImageData | None" = None   # only for kind="image"
```

```python
@dataclass
class ImageData:
    mime_type: str          # "image/png", "image/jpeg", …
    base64_data: str        # raw base64 string (no data-URI prefix)
    source: str             # "clipboard", "drag-drop", or a file path
    width: int | None = None
    height: int | None = None
```

### 3.4 Display Echo

After the user submits, print a compact echo so they know what was captured:

| kind | Echo printed |
|---|---|
| `text` (1 line) | *(nothing extra — the prompt `>` already shows it)* |
| `paste` | `  [pasted 12 lines]` |
| `image` | `  [pasted image: 1024×768 PNG]` |

The **full text is still sent to the LLM** — the echo is UI only.

### 3.5 `_prompt_sync()` after refactor

```python
# cli/__main__.py

async def _read_input() -> str:
    loop = asyncio.get_running_loop()
    user_input = await loop.run_in_executor(None, read_user_input)
    _echo_input(user_input)
    return _user_input_to_text(user_input)
```

`_user_input_to_text()`:
- `kind="text"` or `kind="paste"` → `user_input.text` (newline-joined raw lines)
- `kind="image"` → see §4

---

## 4. Image Input

### 4.1 Detection

Two sources:

**A. File path typed/pasted by the user**

If the single-line input matches a valid image file path (`.png`, `.jpg`,
`.jpeg`, `.gif`, `.webp`) that exists on disk, treat it as an image upload
rather than a text message.

```
> /home/user/screenshot.png
  [pasted image: screenshot.png  1920×1080  PNG]
```

**B. Terminal image paste (iTerm2 / Windows Terminal / kitty)**

Some terminals support pasting image data directly via escape sequences or
clipboard. Detecting this reliably cross-platform is hard; we defer this to a
future iteration. For now we only support **file path** images.

### 4.2 Core Layer Changes — `UserMessage` content parts

`UserMessage.content` must become a union type to hold image data.

```python
# core/llm/provider.py

@dataclass
class TextPart:
    type: Literal["text"] = field(default="text", init=False)
    text: str

@dataclass
class ImagePart:
    type: Literal["image_url"] = field(default="image_url", init=False)
    mime_type: str          # "image/png" etc.
    base64_data: str        # raw base64, no prefix

# Content = str | list[TextPart | ImagePart]

@dataclass
class UserMessage:
    role: Literal["user"] = field(default="user", init=False)
    content: str | list[TextPart | ImagePart]
```

`AssistantMessage.content` stays `str` — models don't return images.

### 4.3 Provider Encoding Changes

**`openai.py` — `_encode_messages()`**

```python
def _encode_content(content: str | list) -> str | list:
    if isinstance(content, str):
        return content
    parts = []
    for part in content:
        if isinstance(part, TextPart):
            parts.append({"type": "text", "text": part.text})
        elif isinstance(part, ImagePart):
            parts.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{part.mime_type};base64,{part.base64_data}"
                },
            })
    return parts
```

Then in `_encode_messages()` change:
```python
entry: dict[str, Any] = {"role": msg.role, "content": _encode_content(msg.content)}
```

**`bedrock.py` — `_encode_messages()`**

Bedrock uses a different format for images:
```python
{"image": {"format": "png", "source": {"bytes": base64.b64decode(part.base64_data)}}}
```
Update the Bedrock encoder accordingly.

### 4.4 Session Logging

`user_message` events currently store `{"message_id": ..., "text": ...}`.

When the message contains images, store the parts list instead:

```json
{
  "type": "user_message",
  "data": {
    "message_id": "m_abc123",
    "parts": [
      {"type": "text", "text": "What is in this image?"},
      {"type": "image", "mime_type": "image/png", "source": "screenshot.png", "width": 1920, "height": 1080}
    ]
  }
}
```

The base64 data is **not stored** in the event log (too large). On session
resume, images from previous turns are reconstructed from the source file path
if available, or dropped with a `[image unavailable]` placeholder if the file
no longer exists.

### 4.5 History Reconstruction

`_build_chat_history()` in `__main__.py` must handle both old `text` events and
new `parts` events:

```python
def _parts_to_user_message(data: dict) -> UserMessage:
    if "text" in data:
        return UserMessage(content=data["text"])   # legacy
    parts = []
    for p in data.get("parts", []):
        if p["type"] == "text":
            parts.append(TextPart(text=p["text"]))
        elif p["type"] == "image":
            b64 = _reload_image(p)   # re-reads file or returns placeholder
            if b64:
                parts.append(ImagePart(mime_type=p["mime_type"], base64_data=b64))
            else:
                parts.append(TextPart(text="[image unavailable]"))
    return UserMessage(content=parts)
```

### 4.6 `len(m.content)` in the context estimate

`message_tokens()` in `core/context.py` uses `len(m.content)` to estimate tokens. Guard:

```python
content = m.content if isinstance(m.content, str) else "".join(
    p.text for p in m.content if isinstance(p, TextPart)
)
total += estimate_tokens(content)
```

Note this only counts an image's *text* parts. Images cost real tokens, so the estimate will under-report until the accounting is image-aware.

---

## 5. Affected Files Summary

| File | Change |
|---|---|
| `cli/input.py` | **New.** `read_user_input()`, `UserInput`, `ImageData` |
| `cli/__main__.py` | `_read_input()` delegates to `input.py`; `_log_user_message()` stores parts |
| `cli/context.py` | `replay_messages()` reconstructs content parts |
| `core/context.py` | `message_tokens()` guard for non-str content |
| `core/llm/provider.py` | `TextPart`, `ImagePart` dataclasses; `UserMessage.content` becomes union |
| `core/llm/providers/openai.py` | `_encode_content()` helper; use in `_encode_messages()` |
| `core/llm/providers/bedrock.py` | Image encoding in `_encode_messages()` |
| `CLI_STATUS.md` | Move items to Implemented once done |

---

## 6. Out of Scope (future)

- Clipboard image paste via terminal escape sequences
- Multiple images in one message via drag-and-drop
- Image thumbnail preview in the terminal (sixels / iTerm2 inline images)
- Video / audio input

---

## 7. Implementation Order

1. **`cli/input.py`** — `read_user_input()` with `\` continuation and paste detection (no image yet). Update `_read_input()`. Tests with mock stdin.
2. **`core/llm/provider.py`** — Add `TextPart` / `ImagePart`, update `UserMessage`.
3. **`core/llm/providers/openai.py`** — `_encode_content()`.
4. **`core/llm/providers/bedrock.py`** — image encoding.
5. **`cli/__main__.py`** — image detection in `_read_input()`, `_log_user_message()` parts storage; `replay_messages()` reconstruction in `cli/context.py`; `message_tokens()` guard in `core/context.py`.
6. **Tests** — unit tests for `input.py`; integration test sending an image to a mock provider.
