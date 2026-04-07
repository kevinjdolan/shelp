#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = ROOT / "pyproject.toml"
INIT_PATH = ROOT / "src" / "shelp" / "__init__.py"
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+a-zA-Z0-9\.]*)?$")


def replace_once(text: str, pattern: str, replacement: str, *, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"Could not update {label}.")
    return updated


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("Usage: scripts/bump_version.py <version>")

    version = argv[1].strip()
    if not VERSION_PATTERN.fullmatch(version):
        raise SystemExit(f"Unsupported version '{version}'. Use semantic versions like 0.2.0.")

    pyproject_text = PYPROJECT_PATH.read_text(encoding="utf-8")
    init_text = INIT_PATH.read_text(encoding="utf-8")
    current_match = re.search(r'(?m)^__version__ = "([^"]+)"$', init_text)
    if current_match is None:
        raise SystemExit(f"Could not read the current version from {INIT_PATH}.")
    if current_match.group(1) == version:
        raise SystemExit(f"Version {version} is already current.")

    pyproject_updated = replace_once(
        pyproject_text,
        r'(?m)^version = "[^"]+"$',
        f'version = "{version}"',
        label=str(PYPROJECT_PATH),
    )
    init_updated = replace_once(
        init_text,
        r'(?m)^__version__ = "[^"]+"$',
        f'__version__ = "{version}"',
        label=str(INIT_PATH),
    )

    PYPROJECT_PATH.write_text(pyproject_updated, encoding="utf-8")
    INIT_PATH.write_text(init_updated, encoding="utf-8")
    print(f"Bumped version to {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
