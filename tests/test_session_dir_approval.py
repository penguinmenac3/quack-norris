"""File tools auto-approve operations inside the session's overflow dir."""

from __future__ import annotations

from pathlib import Path

import pytest

SESSION_ID = "sess-abc"


@pytest.fixture()
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("QUACK_NORRIS_HOME", str(tmp_path / "home"))
    p = tmp_path / "project"
    p.mkdir()
    return p


@pytest.fixture()
def tools(project):
    from quack_norris.tools.files import make_file_tools
    return {t.name: t for t in make_file_tools(lambda: project, SESSION_ID)}


@pytest.fixture()
def overflow_file():
    from quack_norris.cli.session import overflow_dir
    return str(overflow_dir(SESSION_ID) / "abc12345.txt")


@pytest.mark.parametrize("name", ["file_view", "file_write", "file_str_replace", "file_delete"])
def test_overflow_paths_auto_approved(tools, overflow_file, name):
    assert tools[name].requires_approval({"path": overflow_file}) is False


@pytest.mark.parametrize("name", ["file_write", "file_str_replace", "file_delete"])
def test_project_paths_still_need_approval(tools, name):
    assert tools[name].requires_approval({"path": "foo.py"}) is True


@pytest.mark.parametrize("name", ["file_view", "file_write", "file_str_replace", "file_delete"])
def test_other_session_dirs_not_auto_approved(tools, name):
    """Only *this* session's overflow dir is exempt — not sibling sessions or meta files."""
    from quack_norris.cli.session import session_dir, sessions_root
    for p in (
        session_dir(SESSION_ID) / "meta.json",
        session_dir(SESSION_ID) / "session.jsonl",
        sessions_root() / "other-session" / "overflow" / "x.txt",
    ):
        assert tools[name].requires_approval({"path": str(p)}) is True, p


def test_move_needs_both_paths_in_overflow(tools, overflow_file):
    mv = tools["file_move"]
    assert mv.requires_approval({"source": overflow_file, "destination": overflow_file}) is False
    assert mv.requires_approval({"source": overflow_file, "destination": "foo.py"}) is True
    assert mv.requires_approval({"source": "foo.py", "destination": overflow_file}) is True


def test_view_project_behaviour_unchanged(tools, project):
    assert tools["file_view"].requires_approval({"path": "foo.py"}) is False
    assert tools["file_view"].requires_approval({"path": str(project.parent / "outside.py")}) is True


def test_without_session_id_nothing_is_exempt(project, overflow_file):
    from quack_norris.tools.files import make_file_tools
    tools = {t.name: t for t in make_file_tools(lambda: project)}
    assert tools["file_write"].requires_approval({"path": overflow_file}) is True
    assert tools["file_view"].requires_approval({"path": overflow_file}) is True


def test_overflow_sink_writes_into_auto_approved_dir(tools, monkeypatch):
    """The sink's output path must be one the file tools auto-approve."""
    from quack_norris.cli.context import make_overflow_sink
    path = make_overflow_sink(SESSION_ID)("spilled output")
    assert tools["file_view"].requires_approval({"path": path}) is False
    assert tools["file_delete"].requires_approval({"path": path}) is False
    assert Path(path).read_text(encoding="utf-8") == "spilled output"
