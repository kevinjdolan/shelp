from __future__ import annotations


class ShelpError(Exception):
    """Raised for expected helper failures that should be shown to the user."""

    def __init__(self, message: str, *, stage: str | None = None) -> None:
        super().__init__(message)
        self.stage = stage
