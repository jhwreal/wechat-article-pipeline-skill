#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from atomic_files import atomic_write_json


def new_publish_run(
    legacy_fields: Mapping[str, Any],
    *,
    manifest_sha256: str,
    requested_operations: Iterable[str],
) -> dict[str, Any]:
    run = dict(legacy_fields)
    run.update(
        {
            "manifest_sha256": manifest_sha256,
            "status": "unknown",
            "operation_state": {
                operation: {"requested": True, "state": "pending"}
                for operation in requested_operations
            },
            "last_error": None,
        }
    )
    return run


def checkpoint(path: Path, run: dict[str, Any]) -> None:
    atomic_write_json(path, run)


def error_details(error: BaseException) -> dict[str, str]:
    return {"type": type(error).__name__, "message": str(error)}


def _operation_entry(run: dict[str, Any], operation: str) -> dict[str, Any]:
    operation_state = run.setdefault("operation_state", {})
    entry = operation_state.setdefault(operation, {"requested": True, "state": "pending"})
    return entry


def mark_started(run: dict[str, Any], operation: str) -> None:
    entry = _operation_entry(run, operation)
    entry["state"] = "in_progress"
    entry.pop("error", None)


def mark_succeeded(run: dict[str, Any], operation: str) -> None:
    entry = _operation_entry(run, operation)
    entry["state"] = "succeeded"
    entry.pop("error", None)


def mark_failed(run: dict[str, Any], operation: str, error: BaseException) -> None:
    details = error_details(error)
    entry = _operation_entry(run, operation)
    entry["state"] = "failed"
    entry["error"] = details
    run["last_error"] = details


def mark_unknown(run: dict[str, Any], operation: str, error: BaseException) -> None:
    details = error_details(error)
    entry = _operation_entry(run, operation)
    entry["state"] = "unknown"
    entry["error"] = details
    run["last_error"] = details
