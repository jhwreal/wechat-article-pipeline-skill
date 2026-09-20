"""Content identity shared by building, publishing and image receipt reuse."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

def compute_source_fingerprint(
    job: dict[str, Any],
    job_dir: Path,
    rendered_visuals: dict[str, str] | None = None,
) -> str:
    import build_wechat_article_workbench as builder

    canonical_job = json.loads(json.dumps(job, ensure_ascii=False))
    for field in ("platform_image_urls", "platform_image_source", "platform_image_fingerprint"):
        canonical_job.pop(field, None)
    canonical_visuals = canonical_job.get("visuals", {}) or {}
    if not isinstance(canonical_visuals, dict):
        raise ValueError("job visuals must be an object")
    for spec in canonical_visuals.values():
        if not isinstance(spec, dict) or not str(spec.get("path", "")).strip():
            continue
        raw_path = Path(str(spec["path"]))
        spec["path"] = str(
            raw_path.resolve()
            if raw_path.is_absolute()
            else (job_dir / raw_path).resolve()
        )
    digest = hashlib.sha256()
    digest.update(b"wechat-publish-source-v1\0")
    digest.update(
        json.dumps(
            canonical_job,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    visuals = job.get("visuals", {}) or {}
    if not isinstance(visuals, dict):
        raise ValueError("job visuals must be an object")
    resolved = dict(rendered_visuals or {})
    for raw_name in sorted(visuals, key=str):
        name = str(raw_name)
        spec = visuals[raw_name]
        if not isinstance(spec, dict):
            raise ValueError(f"visual {name!r} must be an object")
        source = resolved.get(name)
        if source is None:
            source, _audit = builder.resolve_image_asset(spec, job_dir)
        digest.update(b"\0visual\0")
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        if source.startswith("data:image/"):
            payload, mime_type = builder.decode_data_uri(source)
            digest.update(mime_type.lower().encode("utf-8"))
            digest.update(b"\0")
            digest.update(payload)
        else:
            digest.update(source.encode("utf-8"))
    # Pasted/local Markdown images are not necessarily in job.visuals.
    for match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", str(job.get("article_markdown", ""))):
        source = match.group(1).strip().strip("<>")
        if source.startswith(("{{visual:", "data:", "https:", "http:")):
            continue
        path = Path(source)
        path = path if path.is_absolute() else job_dir / path
        digest.update(b"\0markdown-image\0")
        digest.update(str(path.resolve()).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def validate_source_freshness(manifest: dict[str, Any]) -> None:
    workbench = str(manifest.get("workbench_html") or "").strip()
    source_job = str(manifest.get("source_job") or "").strip()
    if not workbench and not source_job:
        if manifest.get("source_fingerprint"):
            raise ValueError("manifest has a fingerprint but no source location; regenerate it")
        return  # Self-contained legacy/API manifests have no live source binding.
    job_path = Path(workbench).expanduser().resolve().with_suffix(".job.json") if workbench else Path(source_job).expanduser().resolve()
    if not job_path.is_file():
        raise ValueError("current source job is missing; regenerate the publish manifest")
    job = json.loads(job_path.read_text(encoding="utf-8"))
    expected = str(manifest.get("source_fingerprint") or "")
    if not expected or compute_source_fingerprint(job, job_path.parent) != expected:
        raise ValueError("publish manifest is stale: source content or images changed; regenerate it")
    if workbench:
        html = Path(workbench).expanduser().resolve()
        if not html.is_file():
            raise ValueError("current workbench is missing")
        sidecar = html.parent / "support" / (html.stem + ".workbench-state.json")
        if sidecar.is_file():
            state = json.loads(sidecar.read_text(encoding="utf-8"))
            source = manifest.get("source_state") or {}
            if state.get("recovery_required") or (state.get("manifest") or {}).get("state") not in {"ready", "not_configured"}:
                raise ValueError("workbench manifest refresh/recovery is incomplete")
            if int(state.get("coreRevision", 0)) != int(source.get("core_revision", 0)):
                raise ValueError("publish manifest belongs to an older workbench revision")
