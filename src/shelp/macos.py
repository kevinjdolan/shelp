from __future__ import annotations

import plistlib
import subprocess
import sys
import textwrap
from pathlib import Path

from .hotkeys import DEFAULT_TRANSLATE_HOTKEY, applescript_control_key


QUICK_ACTION_NAME = "SHelp Trigger"


def is_macos() -> bool:
    return sys.platform == "darwin"


def quick_action_path() -> Path:
    return Path.home() / "Library" / "Services" / f"{QUICK_ACTION_NAME}.workflow"


def build_quick_action_info_plist() -> bytes:
    payload = {
        "CFBundleDevelopmentRegion": "en_US",
        "CFBundleIdentifier": "dev.shelp.services.trigger",
        "CFBundleName": QUICK_ACTION_NAME,
        "CFBundleShortVersionString": "1.0",
        "NSServices": [
            {
                "NSMenuItem": {"default": QUICK_ACTION_NAME},
                "NSMessage": "runWorkflowAsService",
                "NSSendTypes": ["public.utf8-plain-text"],
            }
        ],
    }
    return plistlib.dumps(payload, fmt=plistlib.FMT_XML)


def build_quick_action_document(*, hotkey: str = DEFAULT_TRANSLATE_HOTKEY) -> bytes:
    control_key = applescript_control_key(hotkey)
    shell_script = textwrap.dedent(
        f"""\
        /usr/bin/osascript <<'APPLESCRIPT'
        tell application "System Events"
            keystroke "{control_key}" using control down
        end tell
        APPLESCRIPT
        """
    )
    workflow = {
        "actions": [
            {
                "action": {
                    "ActionBundlePath": "/System/Library/Automator/Run Shell Script.action",
                    "ActionName": "Run Shell Script",
                    "ActionParameters": {
                        "CheckedForUserDefaultShell": True,
                        "COMMAND_STRING": shell_script,
                        "inputMethod": 0,
                        "shell": "/bin/zsh",
                        "source": "",
                    },
                    "AMAccepts": {
                        "Container": "List",
                        "Optional": True,
                        "Types": ["com.apple.cocoa.string"],
                    },
                    "AMActionVersion": "2.0.3",
                    "AMApplication": ["Automator"],
                    "AMParameterProperties": {
                        "CheckedForUserDefaultShell": {},
                        "COMMAND_STRING": {},
                        "inputMethod": {},
                        "shell": {},
                        "source": {},
                    },
                    "AMProvides": {
                        "Container": "List",
                        "Types": ["com.apple.cocoa.string"],
                    },
                    "arguments": {
                        "0": {
                            "default value": 0,
                            "name": "inputMethod",
                            "required": "0",
                            "type": "0",
                            "uuid": "0",
                        },
                        "1": {
                            "default value": "",
                            "name": "source",
                            "required": "0",
                            "type": "0",
                            "uuid": "1",
                        },
                        "2": {
                            "default value": False,
                            "name": "CheckedForUserDefaultShell",
                            "required": "0",
                            "type": "0",
                            "uuid": "2",
                        },
                        "3": {
                            "default value": "",
                            "name": "COMMAND_STRING",
                            "required": "0",
                            "type": "0",
                            "uuid": "3",
                        },
                        "4": {
                            "default value": "/bin/sh",
                            "name": "shell",
                            "required": "0",
                            "type": "0",
                            "uuid": "4",
                        },
                    },
                    "BundleIdentifier": "com.apple.RunShellScript",
                    "CanShowSelectedItemsWhenRun": False,
                    "CanShowWhenRun": True,
                    "Category": ["AMCategoryUtilities"],
                    "CFBundleVersion": "2.0.3",
                    "Class Name": "RunShellScriptAction",
                    "InputUUID": "E2E7AA0E-27EF-4E51-9666-7F7B4E9BC101",
                    "OutputUUID": "F50290D8-1E76-49A2-BB42-1ECF5D65AC9B",
                    "UUID": "A0E6AF54-1E2A-4BB8-B898-2E6D6C80876F",
                    "Keywords": ["Shell", "Script", "Command", "Run", "Unix"],
                    "nibPath": "/System/Library/Automator/Run Shell Script.action/Contents/Resources/en.lproj/main.nib",
                    "UnlocalizedApplications": ["Automator"],
                },
                "isViewVisible": True,
            }
        ],
        "AMApplicationBuild": "381",
        "AMApplicationVersion": "2.4",
        "AMDocumentVersion": "2",
        "connectors": {},
        "workflowMetaData": {
            "serviceApplicationBundleID": "",
            "serviceApplicationPath": "",
            "serviceInputTypeIdentifier": "com.apple.Automator.text",
            "serviceOutputTypeIdentifier": "com.apple.Automator.nothing",
            "serviceProcessesInput": 0,
            "workflowTypeIdentifier": "com.apple.Automator.servicesMenu",
        },
    }
    return plistlib.dumps(workflow, fmt=plistlib.FMT_XML)


def refresh_services_menu() -> None:
    if not is_macos():
        return
    subprocess.run(
        ["/usr/bin/killall", "pbs"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def install_quick_action(
    *,
    force: bool = False,
    refresh: bool = True,
    hotkey: str = DEFAULT_TRANSLATE_HOTKEY,
) -> Path | None:
    if not is_macos():
        return None

    bundle_path = quick_action_path()
    contents_path = bundle_path / "Contents"
    resources_path = contents_path / "Resources"
    resources_path.mkdir(parents=True, exist_ok=True)

    info_path = contents_path / "Info.plist"
    document_path = resources_path / "document.wflow"

    info_bytes = build_quick_action_info_plist()
    document_bytes = build_quick_action_document(hotkey=hotkey)

    if force or not info_path.exists() or info_path.read_bytes() != info_bytes:
        info_path.write_bytes(info_bytes)
    if force or not document_path.exists() or document_path.read_bytes() != document_bytes:
        document_path.write_bytes(document_bytes)

    if refresh:
        refresh_services_menu()

    return bundle_path
