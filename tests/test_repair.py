from __future__ import annotations

from shelp.repair import infer_repair_target


def test_infer_repair_target_prefers_explicit_command() -> None:
    target = infer_repair_target([(127, "rg TODO src")], explicit_command="grep TODO README.md")

    assert target is not None
    assert target.command == "grep TODO README.md"
    assert target.source == "explicit"
    assert target.exit_status is None


def test_infer_repair_target_prefers_recent_failure() -> None:
    target = infer_repair_target(
        [
            (0, "pwd"),
            (127, "git chekcout main"),
            (0, "ls"),
        ]
    )

    assert target is not None
    assert target.command == "git chekcout main"
    assert target.source == "last_failed"
    assert target.exit_status == 127


def test_infer_repair_target_falls_back_to_last_command() -> None:
    target = infer_repair_target([(0, "pwd"), (0, "ls -la")])

    assert target is not None
    assert target.command == "ls -la"
    assert target.source == "last_command"
    assert target.exit_status == 0
