#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Mapping


def atomic_write_text(path: Path, text: str, *, mode: int | None = None) -> None:
    path = path.expanduser()
    payload = text.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    target_mode = mode
    if target_mode is None and path.exists():
        target_mode = stat.S_IMODE(path.stat().st_mode)

    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if target_mode is not None:
            os.chmod(temp_name, target_mode)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def atomic_write_json(path: Path, data: Mapping[str, Any], *, mode: int | None = None) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(path, text, mode=mode)


def manifest_fingerprint(path: Path) -> str:
    return hashlib.sha256(path.expanduser().read_bytes()).hexdigest()
