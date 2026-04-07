from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class RepairTarget:
    command: str
    exit_status: int | None
    source: Literal["explicit", "last_failed", "last_command"]


def infer_repair_target(
    recent_commands: list[tuple[int | None, str]],
    *,
    explicit_command: str = "",
) -> RepairTarget | None:
    explicit_command = explicit_command.strip()
    if explicit_command:
        return RepairTarget(command=explicit_command, exit_status=None, source="explicit")

    for exit_status, command_text in reversed(recent_commands):
        if exit_status not in {None, 0}:
            return RepairTarget(command=command_text, exit_status=exit_status, source="last_failed")

    if not recent_commands:
        return None

    exit_status, command_text = recent_commands[-1]
    return RepairTarget(command=command_text, exit_status=exit_status, source="last_command")


def repair_context_lines(target: RepairTarget | None) -> list[str]:
    if target is None:
        return [
            "- Repair mode: active.",
            "- Repair target command: unavailable. Ask for the command or goal only if you cannot produce a best-effort repair.",
        ]

    status_label = "unknown" if target.exit_status is None else str(target.exit_status)
    source_label = {
        "explicit": "current shell buffer",
        "last_failed": "most recent failing command",
        "last_command": "most recent command",
    }[target.source]
    return [
        "- Repair mode: active.",
        f"- Repair target ({source_label}): exit {status_label}: {target.command}",
    ]


def repair_intro_message(target: RepairTarget | None) -> str:
    if target is None:
        return "I could not find a recent command to repair. Paste the command or say what you were trying to do."

    if target.source == "explicit":
        return "I am going to repair that command and use your recent shell history as context."

    if target.source == "last_failed":
        status_label = "unknown" if target.exit_status is None else str(target.exit_status)
        return f"I picked your most recent failing command (exit {status_label}) and I am going to repair it."

    return "I did not see a recent failing command, so I am starting from your most recent command."
