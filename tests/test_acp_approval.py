from __future__ import annotations

from quack_norris.acp.approval import ApprovalPolicy


def test_shell_choices_include_scopes_variants_and_reject(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QUACK_NORRIS_HOME", str(tmp_path / "home"))
    policy = ApprovalPolicy(tmp_path / "project")

    choices = policy.choices("pwsh", {"command": 'git status --short'})

    assert [choice.option.option_id for choice in choices] == [
        "allow_once",
        "allow_project_exact",
        "allow_global_exact",
        "allow_project_command",
        "allow_global_command",
        "reject_once",
    ]
    assert choices[-1].option.kind == "reject_once"
    assert choices[3].rule.pattern == "git *"


def test_move_rule_includes_source_and_destination(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QUACK_NORRIS_HOME", str(tmp_path / "home"))
    policy = ApprovalPolicy(tmp_path)

    choices = policy.choices(
        "file_move",
        {"source": "src/old.txt", "destination": "dst/new.txt"},
    )

    assert choices[1].rule.pattern == "src/old.txt -> dst/new.txt"


def test_project_rule_is_persisted_and_matched(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QUACK_NORRIS_HOME", str(tmp_path / "home"))
    project = tmp_path / "project"
    project.mkdir()
    policy = ApprovalPolicy(project)
    choice = next(
        choice
        for choice in policy.choices("bash", {"command": "uv run pytest"})
        if choice.option.option_id == "allow_project_exact"
    )

    policy.persist(choice)

    assert policy.is_allowed("bash", {"command": "uv run pytest"}) is True
    assert policy.is_allowed("bash", {"command": "uv run ruff check"}) is False
    assert (project / ".quack-whitelist.yaml").exists()


def test_global_command_rule_matches_variants(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QUACK_NORRIS_HOME", str(tmp_path / "home"))
    project = tmp_path / "project"
    project.mkdir()
    policy = ApprovalPolicy(project)
    choice = next(
        choice
        for choice in policy.choices("pwsh", {"command": "git status"})
        if choice.option.option_id == "allow_global_command"
    )

    policy.persist(choice)

    other_project = tmp_path / "other"
    other_project.mkdir()
    other_policy = ApprovalPolicy(other_project)
    assert other_policy.is_allowed("pwsh", {"command": "git diff"}) is True
    assert (tmp_path / "home" / "whitelist.yaml").exists()
