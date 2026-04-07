from __future__ import annotations

import argparse
import json
import sys

from .config import config_path, load_config, migrate_legacy_config, resolve_hotkey_bindings, save_config
from .hotkeys import display_hotkey
from .macos import install_quick_action, is_macos, quick_action_path
from .session import run_cli_session
from .shells import SUPPORTED_SHELLS, default_shells_to_install, install_shell_loader, shell_init


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shelp", description="AI shell helper")
    subparsers = parser.add_subparsers(dest="command")

    session_parser = subparsers.add_parser("session", help="Run the interactive helper session")
    session_parser.add_argument("--initial-buffer", default="")

    repair_parser = subparsers.add_parser("repair", help="Repair a recent shell command using recent history")
    repair_parser.add_argument("--initial-buffer", default="")

    init_parser = subparsers.add_parser("init", help="Print shell integration code")
    init_parser.add_argument("shell", choices=SUPPORTED_SHELLS)

    install_parser = subparsers.add_parser("install", help="Install shell and macOS integrations")
    install_parser.add_argument("--shell", dest="shells", action="append", choices=SUPPORTED_SHELLS)
    install_parser.add_argument("--all-shells", action="store_true")
    install_parser.add_argument("--force", action="store_true")
    install_parser.add_argument("--skip-config-migration", action="store_true")
    install_parser.add_argument("--no-macos-quick-action", action="store_true")
    install_parser.add_argument("--translate-hotkey")
    install_parser.add_argument("--repair-hotkey")

    macos_parser = subparsers.add_parser("macos", help="Manage macOS-specific integrations")
    macos_subparsers = macos_parser.add_subparsers(dest="macos_command")
    macos_install = macos_subparsers.add_parser("install-quick-action", help="Install the macOS Quick Action")
    macos_install.add_argument("--force", action="store_true")

    paths_parser = subparsers.add_parser("paths", help="Show important filesystem paths")
    paths_parser.add_argument("--json", action="store_true")

    return parser


def _print_paths(*, as_json: bool) -> int:
    payload = {
        "config": str(config_path()),
        "macos_quick_action": str(quick_action_path()) if is_macos() else None,
    }
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv:
        return run_cli_session("")

    if argv[0] in {"-h", "--help"}:
        build_parser().print_help()
        return 0

    if argv[0].startswith("-"):
        parser = argparse.ArgumentParser(prog="shelp")
        parser.add_argument("--initial-buffer", default="")
        args = parser.parse_args(argv)
        return run_cli_session(args.initial_buffer)

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "session":
        return run_cli_session(args.initial_buffer)

    if args.command == "repair":
        return run_cli_session(args.initial_buffer, session_mode="repair")

    if args.command == "init":
        print(shell_init(args.shell), end="")
        return 0

    if args.command == "install":
        if args.all_shells:
            shell_names = list(SUPPORTED_SHELLS)
        elif args.shells:
            shell_names = list(dict.fromkeys(args.shells))
        else:
            shell_names = default_shells_to_install()

        config = load_config()
        hotkey_bindings = resolve_hotkey_bindings(
            config,
            translate_hotkey=args.translate_hotkey,
            repair_hotkey=args.repair_hotkey,
        )
        saved_config = False
        if args.translate_hotkey is not None or args.repair_hotkey is not None:
            hotkeys_changed = (
                config.get("translate_hotkey", "").strip() != hotkey_bindings.translate
                or config.get("repair_hotkey", "").strip() != hotkey_bindings.repair
            )
            if hotkeys_changed:
                config["translate_hotkey"] = hotkey_bindings.translate
                config["repair_hotkey"] = hotkey_bindings.repair
                save_config(config)
                saved_config = True
                print(f"Saved shell hotkeys to {config_path()}")
            print(f"Translate hotkey: {display_hotkey(hotkey_bindings.translate)}")
            print(f"Repair hotkey: {display_hotkey(hotkey_bindings.repair)}")

        changed_paths = []
        for shell_name in shell_names:
            changed_paths.extend(install_shell_loader(shell_name, force=args.force))

        for path in changed_paths:
            print(path)

        if not args.skip_config_migration and not saved_config:
            migrated = migrate_legacy_config(force=args.force)
            if migrated is not None:
                print(f"Migrated config to {migrated}")

        if is_macos() and not args.no_macos_quick_action:
            quick_action = install_quick_action(force=args.force, hotkey=hotkey_bindings.translate)
            if quick_action is not None:
                print(quick_action)
                print("Assign a keyboard shortcut to 'SHelp Trigger' in System Settings > Keyboard > Keyboard Shortcuts > Services.")

        return 0

    if args.command == "macos":
        if args.macos_command == "install-quick-action":
            if not is_macos():
                print("The macOS Quick Action is only available on macOS.", file=sys.stderr)
                return 1
            hotkey_bindings = resolve_hotkey_bindings(load_config())
            quick_action = install_quick_action(force=args.force, hotkey=hotkey_bindings.translate)
            if quick_action is not None:
                print(quick_action)
            return 0
        parser.error("a macos subcommand is required")

    if args.command == "paths":
        return _print_paths(as_json=args.json)

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
