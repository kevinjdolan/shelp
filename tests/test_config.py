from __future__ import annotations

from pathlib import Path

from shelp.config import config_path, load_config, migrate_legacy_config


def test_load_config_falls_back_to_legacy(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    legacy_path = tmp_path / ".config" / "fish" / "ai_help.yaml"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text("provider: anthropic\nanthropic_model: claude-sonnet-4-6\n", encoding="utf-8")

    loaded = load_config()

    assert loaded["provider"] == "anthropic"
    assert loaded["anthropic_model"] == "claude-sonnet-4-6"


def test_migrate_legacy_config_writes_new_primary_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    legacy_path = tmp_path / ".config" / "fish" / "ai_help.yaml"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text("provider: openai\nopenai_model: gpt-4.1-mini\n", encoding="utf-8")

    migrated_path = migrate_legacy_config()

    assert migrated_path == config_path()
    assert migrated_path is not None
    assert migrated_path.exists()
    assert "openai_model: gpt-4.1-mini" in migrated_path.read_text(encoding="utf-8")
