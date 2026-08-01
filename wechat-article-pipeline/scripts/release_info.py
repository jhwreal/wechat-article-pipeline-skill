from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parents[1]
VERSION_PATH = SKILL_ROOT / "VERSION"
PLATFORM_ADAPTERS_PATH = SKILL_ROOT / "references" / "platform-adapters.json"
SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


def skill_version() -> str:
    version = VERSION_PATH.read_text(encoding="utf-8").strip()
    if not SEMVER_RE.fullmatch(version):
        raise ValueError(f"invalid skill version in {VERSION_PATH}: {version!r}")
    return version


def platform_adapters(path: Path = PLATFORM_ADAPTERS_PATH) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported platform adapter schema")
    adapters = {
        name: value
        for name, value in payload.items()
        if name != "schema_version" and isinstance(value, dict)
    }
    if set(adapters) != {"wechat", "toutiao", "xiaohongshu"}:
        raise ValueError("platform adapters must define wechat, toutiao, and xiaohongshu")
    expected_headings = {f"H{level}" for level in range(1, 7)}
    for name, adapter in adapters.items():
        for key in (
            "version",
            "displayName",
            "optionLabel",
            "panelTitle",
            "panelDesc",
            "previewLabel",
            "copyLabel",
            "headingMap",
            "imagePolicy",
            "nativeSelection",
        ):
            if key not in adapter:
                raise ValueError(f"platform adapter {name} is missing {key}")
        heading_map = adapter["headingMap"]
        if not isinstance(heading_map, dict) or set(heading_map) != expected_headings:
            raise ValueError(f"platform adapter {name} must map H1 through H6")
        if not set(heading_map.values()) <= expected_headings:
            raise ValueError(f"platform adapter {name} has an invalid heading target")
        if adapter["imagePolicy"] not in {"embedded-data", "hosted-url", "absolute-url"}:
            raise ValueError(f"platform adapter {name} has an invalid image policy")
        if not isinstance(adapter["nativeSelection"], bool):
            raise ValueError(f"platform adapter {name} nativeSelection must be boolean")
        title_max = adapter.get("titleMax")
        if title_max is not None and (isinstance(title_max, bool) or int(title_max) <= 0):
            raise ValueError(f"platform adapter {name} titleMax must be positive or null")
    return adapters


def workbench_build_info(template_path: Path) -> dict[str, Any]:
    adapters = platform_adapters()
    return {
        "skillVersion": skill_version(),
        "workbenchSchemaVersion": 3,
        "templateAsset": template_path.name,
        "templateSha256": hashlib.sha256(template_path.read_bytes()).hexdigest()[:16],
        "platformAdaptersSha256": hashlib.sha256(
            PLATFORM_ADAPTERS_PATH.read_bytes()
        ).hexdigest()[:16],
        "platformAdapterVersions": {
            name: str(adapter.get("version") or "unknown")
            for name, adapter in adapters.items()
        },
    }
