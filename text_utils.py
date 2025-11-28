"""Text normalization helpers."""
from __future__ import annotations

import re


_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str | None) -> str:
    """Lowercase and collapse whitespace for consistent comparisons."""

    if not text:
        return ""
    lowered = text.strip().lower()
    return _WHITESPACE_RE.sub(" ", lowered)


__all__ = ["normalize_text"]
