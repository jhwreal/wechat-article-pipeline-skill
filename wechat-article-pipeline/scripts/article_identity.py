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


def markdown_source_snapshot(path: Path, payload: bytes | None = None) -> dict[str, str]:
    path = path.expanduser().resolve()
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes() if payload is None else payload).hexdigest(),
    }


def _legacy_markdown_source(markdown: str, job: dict[str, Any], job_dir: Path, source_dir: Path) -> str:
    """Only reconcile known path/front-matter representations for old packages.

    Formatting transformations such as automatic focus marking cannot be proven
    after the fact. Such old packages must be rebuilt to capture a source hash.
    """
    import build_wechat_article_workbench as builder

    markdown, _metadata = builder.split_front_matter(markdown)
    paths = {}
    for name, spec in (job.get("visuals") or {}).items():
        if isinstance(spec, dict) and spec.get("path"):
            path = Path(spec["path"])
            paths[name] = str((path if path.is_absolute() else job_dir / path).resolve())
    markdown, _missing = builder.replace_visual_placeholders(markdown, paths)

    def absolute_image(match: re.Match[str]) -> str:
        target = match.group(2).strip().strip("<>")
        if not target.startswith(("{{visual:", "data:", "http:", "https:")):
            path = Path(target)
            target = str((path if path.is_absolute() else source_dir / path).resolve())
        return f"![{match.group(1)}]({target})"

    return re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", absolute_image, markdown).strip()


def source_markdown_receipt(
    job: dict[str, Any], job_dir: Path, fallback_path: Path | None = None,
) -> dict[str, Any]:
    """Validate the canonical Markdown and freeze its delivery identity once.

    New jobs record the original source before focus/image transformations. Old
    jobs may only attest a companion Markdown that still matches their content.
    Jobs with no Markdown companion remain usable, without a Markdown receipt.
    """
    snapshot = job.get("source_markdown")
    if snapshot is not None:
        if (not isinstance(snapshot, dict) or not snapshot.get("path")
                or not re.fullmatch(r"[0-9a-f]{64}", str(snapshot.get("sha256", "")))):
            raise ValueError("source Markdown snapshot is invalid; regenerate the article package")
        source_path = Path(snapshot["path"]).expanduser().resolve()
    elif fallback_path is not None and fallback_path.is_file():
        source_path = fallback_path.resolve()
    else:
        return {}
    payload = source_path.read_bytes()
    observed = markdown_source_snapshot(source_path, payload)
    if snapshot is not None and observed != snapshot:
        raise ValueError("publish manifest is stale: source Markdown changed; regenerate the article package")
    # Match Path.read_text() newline behavior used by three-platform state.
    markdown = payload.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    if snapshot is None and _legacy_markdown_source(markdown, job, job_dir, source_path.parent) != _legacy_markdown_source(
        str(job.get("article_markdown", "")), job, job_dir, job_dir,
    ):
        raise ValueError("publish manifest is stale: source Markdown differs from the job; regenerate the article package")
    visuals = json.loads(json.dumps(job.get("visuals") or {}))
    for spec in visuals.values():
        if isinstance(spec, dict) and spec.get("path"):
            path = Path(spec["path"])
            spec["path"] = str((path if path.is_absolute() else job_dir / path).resolve())
    return {
        "source_markdown": observed,
        "delivery_source_fingerprint": compute_source_fingerprint(
            {"article_markdown": markdown, "visuals": visuals}, source_path.parent,
        ),
    }


def validate_source_freshness(manifest: dict[str, Any]) -> dict[str, Any]:
    workbench = str(manifest.get("workbench_html") or "").strip()
    source_job = str(manifest.get("source_job") or "").strip()
    if not workbench and not source_job:
        if manifest.get("source_fingerprint"):
            raise ValueError("manifest has a fingerprint but no source location; regenerate it")
        return {}  # Standalone legacy/API manifests cannot attest a live Markdown revision.
    job_path = Path(workbench).expanduser().resolve().with_suffix(".job.json") if workbench else Path(source_job).expanduser().resolve()
    if not job_path.is_file():
        raise ValueError("current source job is missing; regenerate the publish manifest")
    job = json.loads(job_path.read_text(encoding="utf-8"))
    expected = str(manifest.get("source_fingerprint") or "")
    if not expected or compute_source_fingerprint(job, job_path.parent) != expected:
        raise ValueError("publish manifest is stale: source content or images changed; regenerate it")
    markdown_path = (Path(workbench).expanduser().resolve().with_suffix(".md") if workbench
                     else job_path.with_name(job_path.name.removesuffix(".job.json") + ".md"))
    receipt = source_markdown_receipt(job, job_path.parent, markdown_path)
    for key in ("source_markdown", "delivery_source_fingerprint"):
        if key in manifest and manifest[key] != receipt.get(key):
            raise ValueError("publish manifest is stale: Markdown source snapshot changed; regenerate it")
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
            # A full package rebuild is not a browser revision. Its freshly
            # rendered HTML must carry the same source snapshot as the current
            # job and manifest before an old, otherwise-ready sidecar can be
            # disregarded. Failed refresh/recovery states above stay closed.
            rebuilt = False
            if not source and manifest.get("source_markdown") and job.get("source_markdown") == receipt.get("source_markdown"):
                import build_wechat_article_workbench as builder
                bootstrap = builder.read_bootstrap(html.read_text(encoding="utf-8"))
                rebuilt = bootstrap.get("sourceMarkdown") == receipt["source_markdown"]
            if not rebuilt and int(state.get("coreRevision", 0)) != int(source.get("core_revision", 0)):
                raise ValueError("publish manifest belongs to an older workbench revision")
    return receipt


def delivery_source_fingerprint(markdown_path: Path) -> str:
    markdown_path = markdown_path.expanduser().resolve()
    job_path = markdown_path.with_suffix(".job.json")
    visuals = {}
    if job_path.is_file():
        visuals = json.loads(job_path.read_text(encoding="utf-8")).get("visuals") or {}
    return compute_source_fingerprint({"article_markdown": markdown_path.read_text(encoding="utf-8"),
                                       "visuals": visuals}, markdown_path.parent)
