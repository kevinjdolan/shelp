from __future__ import annotations

import pytest

from shelp.errors import ShelpError
from shelp.hotkeys import (
    bash_hotkey_sequence,
    build_hotkey_bindings,
    display_hotkey,
    fish_hotkey_sequence,
    zsh_hotkey_sequence,
)


def test_hotkey_sequences_normalize_common_formats() -> None:
    bindings = build_hotkey_bindings("Ctrl-G", "^h")

    assert bindings.translate == "ctrl+g"
    assert bindings.repair == "ctrl+h"
    assert display_hotkey(bindings.translate) == "Ctrl-G"
    assert fish_hotkey_sequence(bindings.translate) == "\\cg"
    assert zsh_hotkey_sequence(bindings.translate) == "^G"
    assert bash_hotkey_sequence(bindings.translate) == "\\C-g"


def test_hotkeys_must_be_distinct() -> None:
    with pytest.raises(ShelpError):
        build_hotkey_bindings("ctrl+g", "CTRL-G")
