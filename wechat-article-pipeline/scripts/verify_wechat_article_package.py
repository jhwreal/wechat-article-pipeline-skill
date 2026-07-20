#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import publish_wechat_api as publisher
import make_wechat_publish_manifest as manifest_builder
from atomic_files import atomic_write_text
from image_jobs_contract import normalize_image_jobs


VISUAL_RE = re.compile(r"\{\{visual:([a-zA-Z0-9_-]+)\}\}")
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
HTML_IMAGE_RE = re.compile(r"<img\b", re.I)
NONPORTABLE_MARKDOWN_IMAGE_RE = re.compile(
    r"!\[[^\]]*\]\((?:file:|/)[^)]+\.(?:png|jpe?g|webp|gif|bmp|svg)\)",
    re.I,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify a generated WeChat article package before delivery.")
    parser.add_argument("html", type=Path, help="Path to files/<slug>.html.")
    parser.add_argument("--job", type=Path, help="Path to files/<slug>.job.json. Defaults to <html>.job.json.")
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Path to files/<slug>.publish-manifest.json. Defaults to <html>.publish-manifest.json if present.",
    )
    parser.add_argument("--images-dir", type=Path, help="Directory expected to contain generated image files.")
    parser.add_argument("--image-jobs", type=Path, help="Path to files/<slug>.image-jobs.json.")
    parser.add_argument("--require-manifest", action="store_true", help="Fail if the publish manifest is missing.")
    parser.add_argument("--out", type=Path, help="Optional JSON report output path.")
    return parser.parse_args()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def add_check(report: dict[str, Any], name: str, ok: bool, detail: str = "") -> None:
    item = {"name": name, "ok": ok}
    if detail:
        item["detail"] = detail
    report["checks"].append(item)
    if not ok:
        report["failures"].append(item)


def default_job_path(html_path: Path) -> Path:
    return html_path.with_suffix(".job.json")


def default_manifest_path(html_path: Path) -> Path:
    return html_path.with_suffix(".publish-manifest.json")


def existing_image(images_dir: Path, output: str) -> bool:
    return (images_dir / output).is_file()


def verify_image_jobs(report: dict[str, Any], image_jobs_path: Path | None, images_dir: Path | None) -> None:
    if not image_jobs_path:
        return
    if not image_jobs_path.exists():
        add_check(report, "image_jobs_exists", False, str(image_jobs_path))
        return
    add_check(report, "image_jobs_exists", True, str(image_jobs_path))
    if not images_dir:
        return
    try:
        payload = normalize_image_jobs(read_json(image_jobs_path))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        add_check(report, "image_jobs_valid", False, str(exc))
        return
    add_check(report, "image_jobs_valid", True, "canonical v2")
    missing: list[str] = []
    for job in payload.get("slots", []):
        output = str(job.get("output", "")).strip()
        if output and not existing_image(images_dir, output):
            missing.append(output)
    add_check(report, "image_jobs_outputs_exist", not missing, ", ".join(missing))


def verify_job(report: dict[str, Any], html_text: str, job_path: Path | None) -> dict[str, Any]:
    if not job_path:
        job_path = default_job_path(Path(report["html"]))
    if not job_path.exists():
        add_check(report, "job_exists", False, str(job_path))
        return {}
    add_check(report, "job_exists", True, str(job_path))
    try:
        job = read_json(job_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        add_check(report, "job_valid", False, str(exc))
        return {}
    if not isinstance(job, dict):
        add_check(report, "job_valid", False, "job JSON must be an object")
        return {}
    add_check(report, "job_valid", True)
    markdown = str(job.get("article_markdown", ""))
    placeholders = sorted(set(VISUAL_RE.findall(markdown)))
    resolved_image_count = len(MARKDOWN_IMAGE_RE.findall(html_text)) + len(HTML_IMAGE_RE.findall(html_text))
    add_check(
        report,
        "workbench_images_cover_placeholders",
        resolved_image_count >= len(placeholders),
        f"resolved_images={resolved_image_count}, placeholders={len(placeholders)}",
    )
    nonportable_refs = NONPORTABLE_MARKDOWN_IMAGE_RE.findall(html_text)
    add_check(
        report,
        "workbench_image_refs_are_portable",
        not nonportable_refs,
        ", ".join(nonportable_refs[:3]),
    )
    missing_paths: list[str] = []
    visuals = job.get("visuals", {}) or {}
    if not isinstance(visuals, dict):
        add_check(report, "visual_paths_exist", False, "job visuals must be an object")
        return job
    for spec in visuals.values():
        if not isinstance(spec, dict) or "path" not in spec:
            continue
        path = Path(str(spec["path"]))
        if not path.is_absolute():
            path = job_path.parent / path
        if not path.is_file():
            missing_paths.append(str(path))
    add_check(report, "visual_paths_exist", not missing_paths, ", ".join(missing_paths))
    return job


def verify_manifest(
    report: dict[str, Any],
    html_path: Path,
    manifest_path: Path | None,
    require_manifest: bool,
    *,
    job_path: Path,
    job: dict[str, Any],
) -> None:
    if not manifest_path:
        manifest_path = default_manifest_path(html_path)
    if not manifest_path.exists():
        add_check(report, "manifest_exists", not require_manifest, str(manifest_path))
        return
    add_check(report, "manifest_exists", True, str(manifest_path))
    try:
        manifest = read_json(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        add_check(report, "manifest_json_valid", False, str(exc))
        return
    if not isinstance(manifest, dict):
        add_check(report, "manifest_json_valid", False, "manifest JSON must be an object")
        return
    add_check(report, "manifest_json_valid", True)
    content_html = str(manifest.get("content_html", ""))
    try:
        validation = publisher.validate_manifest(manifest, content_html)
    except (SystemExit, TypeError, ValueError) as exc:
        add_check(report, "manifest_valid_for_dry_run", False, str(exc))
    else:
        add_check(report, "manifest_valid_for_dry_run", True, json.dumps(validation, ensure_ascii=False))
    source_fingerprint = str(manifest.get("source_fingerprint", "")).strip()
    if source_fingerprint:
        if not job:
            add_check(
                report,
                "manifest_source_matches_job",
                False,
                "cannot verify source fingerprint without a valid job",
            )
        else:
            try:
                current_fingerprint = manifest_builder.compute_source_fingerprint(
                    job,
                    job_path.parent,
                )
            except (OSError, TypeError, ValueError, SystemExit) as exc:
                add_check(report, "manifest_source_matches_job", False, str(exc))
            else:
                add_check(
                    report,
                    "manifest_source_matches_job",
                    current_fingerprint == source_fingerprint,
                    f"manifest={source_fingerprint}, current={current_fingerprint}",
                )
    workbench_html = str(manifest.get("workbench_html", "")).strip()
    if workbench_html:
        add_check(
            report,
            "manifest_matches_html",
            Path(workbench_html).resolve() == html_path.resolve(),
            workbench_html,
        )


def verify_package(
    html_path: Path,
    *,
    job_path: Path | None = None,
    manifest_path: Path | None = None,
    images_dir: Path | None = None,
    image_jobs_path: Path | None = None,
    require_manifest: bool = False,
) -> dict[str, Any]:
    html_path = html_path.resolve()
    report: dict[str, Any] = {"status": "ok", "html": str(html_path), "checks": [], "failures": []}
    if not html_path.exists():
        add_check(report, "html_exists", False, str(html_path))
        report["status"] = "failed"
        return report
    add_check(report, "html_exists", True, str(html_path))
    try:
        html_text = html_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        add_check(report, "html_readable", False, str(exc))
        report["status"] = "failed"
        return report
    add_check(report, "html_readable", True)
    add_check(report, "html_has_content", bool(html_text.strip()))
    add_check(report, "html_has_no_visual_placeholders", "{{visual:" not in html_text)
    resolved_job_path = (job_path or default_job_path(html_path)).resolve()
    job = verify_job(report, html_text, resolved_job_path)
    verify_manifest(
        report,
        html_path,
        manifest_path,
        require_manifest,
        job_path=resolved_job_path,
        job=job,
    )
    verify_image_jobs(report, image_jobs_path, images_dir)
    if report["failures"]:
        report["status"] = "failed"
    return report


def main() -> None:
    args = parse_args()
    report = verify_package(
        args.html,
        job_path=args.job,
        manifest_path=args.manifest,
        images_dir=args.images_dir,
        image_jobs_path=args.image_jobs,
        require_manifest=args.require_manifest,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        atomic_write_text(args.out, text)
    else:
        sys.stdout.write(text)
    if report["status"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
