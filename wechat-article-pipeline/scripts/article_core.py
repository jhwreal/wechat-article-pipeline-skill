from __future__ import annotations

import re


TITLE_RE = re.compile(r"^ {0,3}#(?!#)\s+(.+?)\s*$")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def extract_title(markdown: str, fallback: str = "") -> str:
    """Return the first real Markdown H1, ignoring headings inside fenced code."""
    fence_char = ""
    fence_length = 0
    for line in markdown.splitlines():
        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(1)
            if not fence_char:
                fence_char = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_length:
                fence_char = ""
                fence_length = 0
            continue
        if fence_char:
            continue
        match = TITLE_RE.match(line)
        if match:
            return match.group(1).strip()
    return fallback


def require_title(markdown: str) -> str:
    title = extract_title(markdown)
    if not title:
        raise ValueError(
            "Article markdown must contain a level-1 heading (`# 标题`); "
            "the first H1 is the canonical article title."
        )
    return title
