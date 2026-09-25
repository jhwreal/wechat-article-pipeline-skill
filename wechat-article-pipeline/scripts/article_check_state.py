#!/usr/bin/env python3
"""Hidden, version-bound editorial review ledger; no network or publishing actions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def state_path(article):
    return article.parent / ".article-checks" / (article.name + ".json")


def read_state(article):
    path = state_path(article)
    if not path.exists():
        return {"schema_version": 1, "article": str(article), "checks": []}
    data = json.loads(path.read_text())
    if (data.get("schema_version") != 1 or data.get("article") != str(article)
            or not isinstance(data.get("checks"), list)):
        raise ValueError("Invalid article check state; do not assume checked")
    return data


def status(article):
    article = Path(article).resolve(strict=True)
    sha = digest(article)
    data = read_state(article)
    checks = data["checks"]
    current = []
    for item in checks:
        if item["article_sha256"] != sha or item["scope"] not in ("full", "language"):
            continue
        report = Path(item["report"])
        if report.is_file() and digest(report) == item["report_sha256"]:
            current.append(item)
    return {"article": str(article), "article_sha256": sha,
            "check_count": len(checks), "current_check_count": len(current),
            "needs_check": not bool(current), "current_checks": current}


def record(article, report, expected_sha256, scope):
    article = Path(article).resolve(strict=True)
    report = Path(report).resolve(strict=True)
    if scope not in ("full", "language", "other"):
        raise ValueError("Unknown review scope")
    if digest(article) != expected_sha256:
        raise ValueError("Article changed during review; review the saved version again")
    if report == article or not report.read_text().strip():
        raise ValueError("A separate nonempty review report is required")
    data = read_state(article)
    entry = {"article_sha256": expected_sha256, "scope": scope,
             "report": str(report), "report_sha256": digest(report)}
    # Retrying the same completed report must not increment the counter twice.
    if not any(all(old.get(k) == v for k, v in entry.items()) for old in data["checks"]):
        entry["checked_at"] = datetime.now(timezone.utc).isoformat()
        data["checks"].append(entry)
        path = state_path(article)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".check-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    return status(article)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "record"))
    parser.add_argument("article", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--scope", choices=("full", "language", "other"), default="full")
    args = parser.parse_args()
    try:
        if args.action == "record":
            if not args.report or not args.expected_sha256:
                parser.error("record requires --report and --expected-sha256")
            result = record(args.article, args.report, args.expected_sha256, args.scope)
        else:
            result = status(args.article)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"Check state unavailable: {error}\n")


if __name__ == "__main__":
    main()
