from __future__ import annotations

import plistlib
from pathlib import Path

from shelp.macos import (
    QUICK_ACTION_NAME,
    build_quick_action_document,
    build_quick_action_info_plist,
    install_quick_action,
)


def test_build_quick_action_info_plist_contains_service_name() -> None:
    payload = plistlib.loads(build_quick_action_info_plist())

    assert payload["CFBundleName"] == QUICK_ACTION_NAME
    assert payload["NSServices"][0]["NSMenuItem"]["default"] == QUICK_ACTION_NAME


def test_build_quick_action_document_contains_trigger_keystroke() -> None:
    payload = plistlib.loads(build_quick_action_document())
    action = payload["actions"][0]["action"]

    assert payload["workflowMetaData"]["workflowTypeIdentifier"] == "com.apple.Automator.servicesMenu"
    assert 'keystroke "g" using control down' in action["ActionParameters"]["COMMAND_STRING"]


def test_install_quick_action_writes_bundle(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("shelp.macos.is_macos", lambda: True)

    bundle_path = install_quick_action(refresh=False)

    assert bundle_path is not None
    assert (bundle_path / "Contents" / "Info.plist").exists()
    assert (bundle_path / "Contents" / "Resources" / "document.wflow").exists()
