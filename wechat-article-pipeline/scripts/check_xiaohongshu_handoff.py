"""Check read-only observations before advancing a Xiaohongshu browser handoff."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import sys
from urllib.parse import urlsplit


def check_images(evidence: dict) -> dict:
    expected = evidence["expected_slots"]
    observations = evidence["images"]
    if not isinstance(expected, list) or any(not isinstance(slot, str) or not slot.strip() for slot in expected):
        raise ValueError("expected_slots must list named positions from the source article")
    if len(set(expected)) != len(expected) or not isinstance(observations, list):
        raise ValueError("expected_slots must be unique and images must be a list")

    images = {}
    errors = []
    for observation in observations:
        slot, src = observation["slot"], observation.get("src") or ""
        if not isinstance(src, str) or not isinstance(slot, str):
            raise ValueError("each observed image needs a string slot and src")
        url = urlsplit(src)
        host = url.hostname or ""
        if slot not in expected:
            errors.append(f"unexpected image position: {slot}")
        elif url.scheme != "https" or not (host == "xhscdn.com" or host.endswith(".xhscdn.com")):
            errors.append(f"unverified hosted image at {slot}")
        elif images.get(slot) == src:
            continue  # Duplicate DOM view of the same picture at the same source position.
        elif slot in images or src in images.values():
            errors.append(f"duplicate image or conflicting position: {slot}")
        else:
            images[slot] = src
    missing = [slot for slot in expected if slot not in images]
    if list(images) != [slot for slot in expected if slot in images]:
        errors.append("image order differs from the source")
    return {
        "ok": not missing and not errors,
        "expected_images": len(expected),
        "verified_images": len(images),
        "missing_slots": missing,
        "errors": errors,
    }


def check_submission(evidence: dict) -> dict:
    requested, observed = evidence["requested"], evidence["observed"]
    errors = []
    if evidence.get("submission_maybe_sent") is not False:
        errors.append("submission lock is set or unknown")
    if requested.get("mode") not in ("publish", "schedule"):
        errors.append("no public submission authorized")
    for field in ("mode", "account", "visibility"):
        value = requested.get(field)
        if not isinstance(value, str) or not value.strip() or value != observed.get(field):
            errors.append(f"missing or mismatched {field}")
    if requested.get("mode") == "schedule":
        target = requested.get("beijing_time")
        try:
            parsed = datetime.strptime(target, "%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            errors.append("expected full Beijing date and minute")
        else:
            if parsed.strftime("%Y-%m-%d %H:%M") != target or observed.get("beijing_time") != target:
                errors.append("scheduled Beijing time missing or mismatched")
    return {"ok": not errors, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("check", choices=["images", "pre-submit"])
    parser.add_argument("evidence", type=argparse.FileType("r", encoding="utf-8"), help="local JSON evidence or - for stdin")
    args = parser.parse_args()
    try:
        evidence = json.load(args.evidence)
        result = check_images(evidence) if args.check == "images" else check_submission(evidence)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        result = {"ok": False, "errors": [f"invalid evidence: {exc}"]}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
