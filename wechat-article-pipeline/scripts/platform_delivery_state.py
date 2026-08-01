#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atomic_files import atomic_write_json


PLATFORMS = ("wechat", "toutiao", "xiaohongshu")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def source_fingerprint(markdown_path: Path | None) -> str:
    if markdown_path is None:
        return ""
    return hashlib.sha256(markdown_path.read_bytes()).hexdigest()


def empty_platform_state() -> dict[str, Any]:
    return {
        "status": "pending",
        "mode": "draft",
        "result_file": "",
        "expected": {"images": None, "h1": None, "h2": None},
        "verified": {"images": None, "h1": None, "h2": None},
        "clipboard_strategy": "",
        "draft_verified": False,
        "submission_maybe_sent": False,
        "public_url": "",
        "error": "",
        "updated_at": "",
    }


def new_state(slug: str, title: str, markdown_path: Path | None = None) -> dict[str, Any]:
    now = utc_now()
    return {
        "kind": "three-platform-delivery",
        "schema_version": 1,
        "article": {
            "slug": slug,
            "title": title,
            "source_fingerprint": source_fingerprint(markdown_path),
        },
        "overall_status": "pending",
        "platforms": {name: empty_platform_state() for name in PLATFORMS},
        "created_at": now,
        "updated_at": now,
    }


def validate_state(state: dict[str, Any]) -> None:
    if state.get("kind") != "three-platform-delivery" or state.get("schema_version") != 1:
        raise ValueError("unsupported three-platform delivery state")
    platforms = state.get("platforms")
    if not isinstance(platforms, dict) or set(platforms) != set(PLATFORMS):
        raise ValueError("delivery state must contain exactly three platforms")


def result_status(platform: str, payload: dict[str, Any]) -> str:
    if payload.get("draft_verified") is True:
        return "verified"
    if platform == "wechat" and payload.get("status") == "success":
        return "verified"
    if payload.get("submission_maybe_sent") is True:
        return "unknown"
    raw = str(payload.get("status") or "failed").lower()
    return raw if raw in {"pending", "ready", "verified", "failed", "unknown", "skipped"} else "failed"


def count_value(payload: dict[str, Any], prefix: str, field: str) -> int | None:
    value = payload.get(f"{prefix}_{field}")
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{prefix}_{field} must be an integer")
    return int(value)


def recompute_overall_status(state: dict[str, Any]) -> str:
    statuses = [state["platforms"][name]["status"] for name in PLATFORMS]
    if all(status == "verified" for status in statuses):
        return "verified"
    if any(status == "unknown" for status in statuses):
        return "unknown"
    if any(status == "failed" for status in statuses):
        return "partial_failure"
    if all(status == "pending" for status in statuses):
        return "pending"
    return "in_progress"


def record_result(
    state: dict[str, Any], platform: str, payload: dict[str, Any], result_path: Path
) -> dict[str, Any]:
    validate_state(state)
    if platform not in PLATFORMS:
        raise ValueError(f"unsupported platform: {platform}")
    current = dict(state["platforms"][platform])
    submission_maybe_sent = bool(payload.get("submission_maybe_sent"))
    if current.get("submission_maybe_sent") and not submission_maybe_sent:
        submission_maybe_sent = True
    updated = {
        **current,
        "status": result_status(platform, payload),
        "mode": str(payload.get("mode") or current.get("mode") or "draft"),
        "result_file": str(result_path.resolve()),
        "expected": {
            "images": count_value(payload, "expected", "images"),
            "h1": count_value(payload, "expected", "h1"),
            "h2": count_value(payload, "expected", "h2"),
        },
        "verified": {
            "images": count_value(payload, "verified", "images"),
            "h1": count_value(payload, "verified", "h1"),
            "h2": count_value(payload, "verified", "h2"),
        },
        "clipboard_strategy": str(payload.get("clipboard_strategy") or ""),
        "draft_verified": bool(
            payload.get("draft_verified") or (platform == "wechat" and payload.get("status") == "success")
        ),
        "submission_maybe_sent": submission_maybe_sent,
        "public_url": str(payload.get("public_url") or ""),
        "error": str(payload.get("error") or "")[:500],
        "updated_at": utc_now(),
    }
    state = dict(state)
    state["platforms"] = dict(state["platforms"])
    state["platforms"][platform] = updated
    state["overall_status"] = recompute_overall_status(state)
    state["updated_at"] = utc_now()
    return state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or update resumable three-platform delivery state.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init")
    init.add_argument("state", type=Path)
    init.add_argument("--slug", required=True)
    init.add_argument("--title", required=True)
    init.add_argument("--markdown", type=Path)

    record = subparsers.add_parser("record")
    record.add_argument("state", type=Path)
    record.add_argument("platform", choices=PLATFORMS)
    record.add_argument("result", type=Path)

    summary = subparsers.add_parser("summary")
    summary.add_argument("state", type=Path)
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def main() -> None:
    args = parse_args()
    if args.command == "init":
        if args.state.exists():
            existing = read_json(args.state)
            validate_state(existing)
            article = existing.get("article") or {}
            if article.get("slug") != args.slug or article.get("title") != args.title:
                raise SystemExit("existing delivery state belongs to a different article")
            state = existing
        else:
            state = new_state(args.slug, args.title, args.markdown)
            atomic_write_json(args.state, state)
    elif args.command == "record":
        state = record_result(read_json(args.state), args.platform, read_json(args.result), args.result)
        atomic_write_json(args.state, state)
    else:
        state = read_json(args.state)
        validate_state(state)
    print(json.dumps(state, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
