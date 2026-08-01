from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


def normalize_platform_image_url(value: Any) -> str:
    """Return a public HTTPS image URL suitable for cross-platform rich paste."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return ""
    if not parsed.netloc or parsed.username or parsed.password:
        return ""
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    if scheme == "http" and hostname == "mmbiz.qpic.cn":
        scheme = "https"
    if scheme != "https":
        return ""
    return urlunsplit((scheme, parsed.netloc, parsed.path, parsed.query, parsed.fragment))


def normalize_platform_image_urls(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        return []
    urls = [normalize_platform_image_url(item) for item in value]
    return urls if all(urls) else []


def platform_image_urls_from_wechat_result(result: Any) -> list[str]:
    if not isinstance(result, dict) or result.get("status") != "success":
        return []
    uploads = result.get("body_uploads")
    if not isinstance(uploads, list) or not uploads:
        return []
    values = [
        upload.get("url")
        for upload in uploads
        if isinstance(upload, dict) and upload.get("kind", "body") == "body"
    ]
    return normalize_platform_image_urls(values)


def platform_image_result_path(job_path: Path) -> Path:
    name = job_path.name
    stem = name[: -len(".job.json")] if name.endswith(".job.json") else job_path.stem
    return job_path.with_name(f"{stem}.publish-manifest.wechat-api-result.json")


def discover_platform_image_urls(
    job: dict[str, Any], job_path: Path
) -> tuple[list[str], str]:
    explicit = normalize_platform_image_urls(job.get("platform_image_urls"))
    if explicit:
        return explicit, "job.platform_image_urls"

    result_path = platform_image_result_path(job_path)
    if not result_path.exists():
        return [], ""
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], ""
    urls = platform_image_urls_from_wechat_result(result)
    return (urls, str(result_path.resolve())) if urls else ([], "")
