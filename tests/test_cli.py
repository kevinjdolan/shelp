from __future__ import annotations

from pathlib import Path

from shelp.cli import main
from shelp.config import load_config


def test_install_persists_hotkeys(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("shelp.cli.is_macos", lambda: False)

    result = main(
        [
            "install",
            "--shell",
            "bash",
            "--translate-hotkey",
            "ctrl+t",
            "--repair-hotkey",
            "ctrl+r",
        ]
    )

    assert result == 0
    config = load_config()
    assert config["translate_hotkey"] == "ctrl+t"
    assert config["repair_hotkey"] == "ctrl+r"
