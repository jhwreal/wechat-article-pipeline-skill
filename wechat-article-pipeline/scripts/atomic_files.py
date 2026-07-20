#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Mapping


def fsync_directory(path: Path) -> None:
    """Best-effort durability barrier for directory entry changes."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        # Some filesystems do not support fsync on directories. The file data
        # has still been fsynced before replacement, so keep this best-effort.
        pass
    finally:
        os.close(fd)


def atomic_replace(
    source: Path,
    target: Path,
    *,
    preserve_target_mode: bool = False,
) -> None:
    """Replace target and durably record the affected directory entries."""
    source = source.expanduser()
    target = target.expanduser()
    source_parent = source.parent
    target_parent = target.parent
    if preserve_target_mode and target.exists():
        os.chmod(source, stat.S_IMODE(target.stat().st_mode))
    os.replace(source, target)
    fsync_directory(target_parent)
    if source_parent != target_parent:
        fsync_directory(source_parent)


def atomic_write_bytes(path: Path, payload: bytes, *, mode: int | None = None) -> None:
    path = path.expanduser()
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
        atomic_replace(Path(temp_name), path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def atomic_write_text(path: Path, text: str, *, mode: int | None = None) -> None:
    atomic_write_bytes(path, text.encode("utf-8"), mode=mode)


def atomic_write_json(path: Path, data: Mapping[str, Any], *, mode: int | None = None) -> None:
    text = json.dumps(dict(data), ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(path, text, mode=mode)


def manifest_fingerprint(path: Path) -> str:
    return hashlib.sha256(path.expanduser().read_bytes()).hexdigest()
