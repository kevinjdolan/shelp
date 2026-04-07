from __future__ import annotations

import json
import os
import re
import traceback
from pathlib import Path
from typing import Any

from .errors import ShelpError


def env_value(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value not in {None, ""}:
            return value
    return default


def abbreviate_label(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    if max_length <= 3:
        return text[:max_length]
    head = max(1, (max_length - 1) // 2)
    tail = max(1, max_length - head - 1)
    return f"{text[:head]}…{text[-tail:]}"


def scale_hex_color(value: str, factor: float) -> str:
    channels = [int(value[index:index + 2], 16) for index in (0, 2, 4)]
    scaled = [max(0, min(255, round(channel * factor))) for channel in channels]
    return "".join(f"{channel:02X}" for channel in scaled)


def normalize_command(text: str) -> str:
    raw_text = text.strip()
    code_block = re.search(r"```(?:[a-zA-Z0-9_-]+)?\n(.*?)```", raw_text, re.DOTALL)
    if code_block:
        raw_text = code_block.group(1).strip()

    raw_text = raw_text.strip().strip("`")
    command_lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    return " ".join(command_lines).strip()


def parse_recent_commands() -> list[tuple[int | None, str]]:
    payload = env_value("SHELP_RECENT_COMMANDS", "AI_HELP_RECENT_COMMANDS")
    if not payload:
        return []

    entries: list[tuple[int | None, str]] = []
    for raw_entry in payload.split("\x1e"):
        if not raw_entry:
            continue

        status_text, separator, command_text = raw_entry.partition("\t")
        if not separator:
            continue

        command_text = command_text.strip()
        if not command_text:
            continue

        try:
            exit_status = int(status_text)
        except ValueError:
            exit_status = None

        entries.append((exit_status, command_text))

    return entries[-10:]


def list_filenames_in_cwd(limit: int = 5000) -> list[str]:
    root = Path.cwd()
    names: list[str] = []

    try:
        entries = sorted(root.iterdir(), key=lambda path: path.name.lower())
    except OSError as exc:
        raise ShelpError(
            f"Unable to list files in the current working directory {root}: {exc}",
            stage="reading the current working directory context",
        ) from exc

    for entry in entries[:limit]:
        try:
            suffix = "/" if entry.is_dir() else ""
        except OSError:
            suffix = ""
        names.append(f"{entry.name}{suffix}")

    return names


def build_shared_prompt_context(
    recent_commands: list[tuple[int | None, str]],
    cwd_filenames: list[str],
    *,
    extra_lines: list[str] | None = None,
) -> str:
    lines = [f"- Fully qualified current working directory: {Path.cwd()}"]

    if recent_commands:
        lines.append(f"- Past terminal commands and exit statuses ({len(recent_commands[-10:])} shown):")
        for exit_status, command_text in recent_commands[-10:]:
            status_label = "unknown" if exit_status is None else str(exit_status)
            lines.append(f"  - exit {status_label}: {command_text}")
    else:
        lines.append("- Past terminal commands and exit statuses: unavailable")

    if cwd_filenames:
        lines.append(f"- Filenames in the current working directory ({len(cwd_filenames)} shown, capped at 5000):")
        for name in cwd_filenames:
            lines.append(f"  - {name}")
    else:
        lines.append("- Filenames in the current working directory: no entries found")

    if extra_lines:
        lines.extend(extra_lines)

    return "\n".join(lines)


def excerpt(text: str, limit: int = 240) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1] + "…"


def json_excerpt(value: Any, limit: int = 1000) -> str:
    try:
        serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        serialized = repr(value)
    return excerpt(serialized, limit)


def json_schema_for(model_cls: Any) -> dict[str, Any]:
    schema = model_cls.model_json_schema()
    schema["additionalProperties"] = False
    return schema


def format_traceback_lines(exc: BaseException, *, limit: int = 6) -> list[str]:
    formatted = traceback.format_exception(type(exc), exc, exc.__traceback__)
    lines = [line.rstrip() for chunk in formatted for line in chunk.splitlines() if line.strip()]
    if len(lines) > limit:
        lines = lines[-limit:]
    return lines


def render_exception_report(exc: BaseException, *, default_stage: str | None = None) -> list[str]:
    stage = getattr(exc, "stage", None) or default_stage
    report_lines: list[str] = []

    if stage:
        report_lines.append(f"I could not complete your request while {stage}.")
    else:
        report_lines.append("I could not complete your request.")

    report_lines.append(f"Technical detail: {type(exc).__name__}: {exc}")

    cause = exc.__cause__
    if cause is not None:
        report_lines.append(f"Cause: {type(cause).__name__}: {cause}")

    for trace_line in format_traceback_lines(exc):
        report_lines.append(f"Traceback: {trace_line}")

    return report_lines
