from __future__ import annotations

import sys

import pytest

from quack_norris.tools import make_native_tools


def test_make_native_tools_without_skill_tool(tmp_path) -> None:
    tools = make_native_tools(tmp_path, skills=False)
    names = [tool.name for tool in tools]

    assert names[:5] == [
        "file_view",
        "file_write",
        "file_str_replace",
        "file_move",
        "file_delete",
    ]
    assert ("pwsh" if sys.platform == "win32" else "bash") in names
    assert {"check_tool", "await_tool", "kill_tool"} <= set(names)
    assert "use_skill" not in names


def test_make_native_tools_with_skill_tool(tmp_path) -> None:
    tools = make_native_tools(tmp_path, skills=True)

    assert [tool.name for tool in tools][-1] == "use_skill"


def test_make_native_tools_requires_existing_workspace(tmp_path) -> None:
    with pytest.raises(ValueError, match="existing directory"):
        make_native_tools(tmp_path / "missing", skills=False)
