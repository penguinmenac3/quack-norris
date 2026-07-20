"""Tests for quack_norris.cli.input — paste detection and UserInput logic.

All tests run against the *fallback* path (non-TTY) and the internal
helpers so they work in any CI/pipe environment without a real terminal.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from quack_norris.cli.input import (
    ImageData,
    UserInput,
    _drain_paste_lines,
    _read_user_input_fallback,
    _try_image_path,
    echo_input,
)


# ---------------------------------------------------------------------------
# _read_user_input_fallback — continuation + plain text
# ---------------------------------------------------------------------------

class TestFallback:
    def test_single_line(self):
        with patch("builtins.input", side_effect=["> hello world"]):
            # input() is called with the prompt arg — we just return the value
            with patch("builtins.input", return_value="hello world"):
                ui = _read_user_input_fallback()
        assert ui.kind == "text"
        assert ui.text == "hello world"
        assert ui.raw_lines == ["hello world"]

    def test_continuation(self):
        responses = ["first line\\", "second line\\", "third line"]
        with patch("builtins.input", side_effect=responses):
            ui = _read_user_input_fallback()
        assert ui.kind == "text"
        assert ui.text == "first line\nsecond line\nthird line"
        assert ui.raw_lines == ["first line", "second line", "third line"]

    def test_empty_continuation(self):
        """A blank line after \\ is preserved as an empty line."""
        responses = ["first\\", "", "third"]
        with patch("builtins.input", side_effect=responses):
            ui = _read_user_input_fallback()
        assert ui.text == "first\n\nthird"

    def test_no_continuation_on_plain_line(self):
        with patch("builtins.input", return_value="just one line"):
            ui = _read_user_input_fallback()
        assert ui.text == "just one line"
        assert len(ui.raw_lines) == 1


# ---------------------------------------------------------------------------
# _try_image_path
# ---------------------------------------------------------------------------

class TestImagePathDetection:
    def test_existing_png(self, tmp_path: Path):
        img_file = tmp_path / "screenshot.png"
        img_file.write_bytes(b"")
        result = _try_image_path(str(img_file))
        assert result is not None
        assert result.mime_type == "image/png"
        assert result.source == str(img_file.resolve())

    def test_existing_jpeg(self, tmp_path: Path):
        img_file = tmp_path / "photo.jpg"
        img_file.write_bytes(b"")
        result = _try_image_path(str(img_file))
        assert result is not None
        assert result.mime_type == "image/jpeg"

    def test_quoted_path(self, tmp_path: Path):
        img_file = tmp_path / "my photo.png"
        img_file.write_bytes(b"")
        result = _try_image_path(f'"{img_file}"')
        assert result is not None
        assert result.mime_type == "image/png"

    def test_nonexistent_file(self, tmp_path: Path):
        result = _try_image_path(str(tmp_path / "ghost.png"))
        assert result is None

    def test_non_image_extension(self, tmp_path: Path):
        f = tmp_path / "notes.txt"
        f.write_bytes(b"")
        result = _try_image_path(str(f))
        assert result is None

    def test_plain_text(self):
        result = _try_image_path("hello world")
        assert result is None

    @pytest.mark.parametrize("ext", [".png", ".jpg", ".jpeg", ".gif", ".webp"])
    def test_all_image_extensions(self, tmp_path: Path, ext: str):
        f = tmp_path / f"img{ext}"
        f.write_bytes(b"")
        result = _try_image_path(str(f))
        assert result is not None


# ---------------------------------------------------------------------------
# echo_input
# ---------------------------------------------------------------------------

class TestEchoInput:
    def test_text_no_output(self, capsys):
        ui = UserInput(kind="text", text="hi", raw_lines=["hi"])
        echo_input(ui)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_paste_no_output(self, capsys):
        """Paste echo is printed inline during reading, not via echo_input."""
        ui = UserInput(kind="paste", text="a", raw_lines=["a"])
        echo_input(ui)
        assert capsys.readouterr().out == ""

    def test_echo_paste_helper_singular(self, capsys):
        from quack_norris.cli.input import _echo_paste
        _echo_paste(1)
        assert "[pasted 1 line]" in capsys.readouterr().out

    def test_echo_paste_helper_plural(self, capsys):
        from quack_norris.cli.input import _echo_paste
        _echo_paste(3)
        assert "[pasted 3 lines]" in capsys.readouterr().out

    def test_image_echo(self, capsys, tmp_path: Path):
        img_file = tmp_path / "screenshot.png"
        img_file.write_bytes(b"")
        img_data = ImageData(
            mime_type="image/png",
            base64_data="",
            source=str(img_file.resolve()),
        )
        ui = UserInput(kind="image", text=str(img_file), raw_lines=[str(img_file)], image_data=img_data)
        echo_input(ui)
        out = capsys.readouterr().out
        assert "screenshot.png" in out
        assert "PNG" in out


# ---------------------------------------------------------------------------
# UserInput dataclass
# ---------------------------------------------------------------------------

class TestUserInput:
    def test_defaults(self):
        ui = UserInput(kind="text", text="hi")
        assert ui.raw_lines == []
        assert ui.image_data is None

    def test_paste_kind(self):
        ui = UserInput(kind="paste", text="a\nb", raw_lines=["a", "b"])
        assert ui.kind == "paste"
        assert len(ui.raw_lines) == 2
