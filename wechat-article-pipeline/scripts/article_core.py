from __future__ import annotations

import re


TITLE_RE = re.compile(r"^\s*#\s+(.+?)\s*$", re.M)


def extract_title(markdown: str, fallback: str) -> str:
    match = TITLE_RE.search(markdown)
    return match.group(1).strip() if match else fallback
