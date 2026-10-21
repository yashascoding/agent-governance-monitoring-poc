"""Terminal presentation helpers: ANSI styling and severity colors.

Styling is enabled only for interactive terminals, so piping the CLI output
to a file or a CI log stays plain text. Set ``NO_COLOR`` to force it off or
``FORCE_COLOR`` to force it on.

Colors are never written into persisted artefacts: the alert JSONL files and
the audit report always contain plain text.
"""

from __future__ import annotations

import os
import re
import sys
from typing import TextIO

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"

SEVERITY_COLORS: dict[str, str] = {
    "CRITICAL": BOLD + RED,
    "HIGH": BOLD + YELLOW,
    "MEDIUM": YELLOW,
    "LOW": BLUE,
}

_ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*m")


def supports_color(stream: TextIO | None = None) -> bool:
    """True when ANSI styling should be applied to ``stream``."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    target = stream if stream is not None else sys.stdout
    try:
        return bool(target.isatty())
    except (AttributeError, ValueError):
        return False


def style(text: str, codes: str, *, enabled: bool = True) -> str:
    """Wrap ``text`` in ANSI ``codes`` when styling is enabled."""
    if not enabled or not codes:
        return text
    return f"{codes}{text}{RESET}"


def severity_color(severity: str) -> str:
    """ANSI codes for a severity label; unknown severities fall back to plain."""
    return SEVERITY_COLORS.get(str(severity).upper(), WHITE)


def severity(text: str, *, enabled: bool = True) -> str:
    """Style a severity label (e.g. ``CRITICAL``) with its severity color."""
    return style(str(text), severity_color(text), enabled=enabled)


def bold(text: str, *, enabled: bool = True) -> str:
    return style(text, BOLD, enabled=enabled)


def dim(text: str, *, enabled: bool = True) -> str:
    return style(text, DIM, enabled=enabled)


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from ``text``."""
    return _ANSI_PATTERN.sub("", text)
