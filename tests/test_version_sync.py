from __future__ import annotations

import re
from pathlib import Path

from shelp import __version__


def test_package_version_matches_pyproject() -> None:
    pyproject_text = Path("pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version = "([^"]+)"$', pyproject_text)

    assert match is not None
    assert match.group(1) == __version__
