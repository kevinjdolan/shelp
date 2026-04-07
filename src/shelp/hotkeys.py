from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import ShelpError


DEFAULT_TRANSLATE_HOTKEY = "ctrl+g"
DEFAULT_REPAIR_HOTKEY = "ctrl+h"
_CTRL_HOTKEY_PATTERN = re.compile(r"^ctrl\+([a-z])$")


@dataclass(frozen=True)
class HotkeyBindings:
    translate: str = DEFAULT_TRANSLATE_HOTKEY
    repair: str = DEFAULT_REPAIR_HOTKEY


def _canonicalize_hotkey(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        return ""

    if value.startswith("^") and len(value) == 2 and value[1].isalpha():
        return f"ctrl+{value[1].lower()}"

    normalized = value.lower().replace("control", "ctrl")
    normalized = normalized.replace(" ", "")
    normalized = normalized.replace("-", "+")
    return normalized


def normalize_hotkey(raw_value: str, *, label: str = "hotkey") -> str:
    normalized = _canonicalize_hotkey(raw_value)
    match = _CTRL_HOTKEY_PATTERN.fullmatch(normalized)
    if match:
        return f"ctrl+{match.group(1)}"

    raise ShelpError(
        f"Unsupported {label} '{raw_value}'. Use a control-letter binding like ctrl+g.",
        stage="validating shell hotkeys",
    )


def build_hotkey_bindings(translate_hotkey: str, repair_hotkey: str) -> HotkeyBindings:
    translate = normalize_hotkey(translate_hotkey, label="translate hotkey")
    repair = normalize_hotkey(repair_hotkey, label="repair hotkey")

    if translate == repair:
        raise ShelpError("Translate and repair hotkeys must be different.", stage="validating shell hotkeys")

    return HotkeyBindings(translate=translate, repair=repair)


def _control_letter(hotkey: str) -> str:
    normalized = normalize_hotkey(hotkey)
    return normalized.removeprefix("ctrl+")


def display_hotkey(hotkey: str) -> str:
    return f"Ctrl-{_control_letter(hotkey).upper()}"


def fish_hotkey_sequence(hotkey: str) -> str:
    return f"\\c{_control_letter(hotkey)}"


def zsh_hotkey_sequence(hotkey: str) -> str:
    return f"^{_control_letter(hotkey).upper()}"


def bash_hotkey_sequence(hotkey: str) -> str:
    return f"\\C-{_control_letter(hotkey)}"


def applescript_control_key(hotkey: str) -> str:
    return _control_letter(hotkey)
