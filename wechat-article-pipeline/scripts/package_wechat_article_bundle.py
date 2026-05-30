#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

import build_wechat_article_workbench as builder


WORKSPACE = Path.cwd()
DEFAULT_IMAGE_ROOT = WORKSPACE / "image"
MAKE_PUBLISH_MANIFEST = Path(__file__).resolve().parent / "make_wechat_publish_manifest.py"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
TITLE_RE = re.compile(r"^\s*#\s+(.+?)\s*$", re.M)
WORKBENCH_STORAGE_VERSION = "v9"
WECHAT_COVER_TARGETS = {
    "pic_crop_235_1": {
        "ratio": 2.35,
        "filename": "cover.wechat-235.png",
        "width": 900,
        "height": 383,
    },
    "pic_crop_1_1": {
        "ratio": 1.0,
        "filename": "cover.wechat-1x1.png",
        "width": 900,
        "height": 900,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Package a WeChat article markdown file plus local images into one editable HTML workbench."
    )
    parser.add_argument("article", type=Path, help="Path to the source markdown article.")
    parser.add_argument("out", type=Path, help="Path to the output HTML workbench file.")
    parser.add_argument(
        "--images-dir",
        type=Path,
        help="Directory containing cover/body/closing image files. Defaults to workspace/image/<slug>.",
    )
    parser.add_argument(
        "--plan-json",
        type=Path,
        help="Optional image-plan JSON from make_wechat_article_image_jobs.py so packaging can preserve role metadata.",
    )
    parser.add_argument(
        "--job-out",
        type=Path,
        help="Optional path to save the generated job JSON. Defaults to <output>.job.json.",
    )
    parser.add_argument(
        "--support-dir",
        type=Path,
        help="Optional directory for article/job/quality support files.",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=builder.DEFAULT_TEMPLATE,
        help="Path to the editable HTML workbench template.",
    )
    parser.add_argument("--page-title", help="Optional page title override.")
    parser.add_argument("--brand-title", help="Optional brand title override.")
    parser.add_argument(
        "--brand-subtitle",
        default="单文件 HTML · 含正文和配图 · 可继续编辑",
        help="Optional brand subtitle.",
    )
    parser.add_argument(
        "--theme-color",
        default="#17b394",
        help="Theme color injected into the HTML workbench.",
    )
    parser.add_argument("--storage-key", help="Optional storage key override.")
    parser.add_argument(
        "--publish-manifest-out",
        type=Path,
        help="Optional path to save the WeChat API draft manifest. Defaults to <html-stem>.publish-manifest.json.",
    )
    parser.add_argument(
        "--no-publish-manifest",
        action="store_true",
        help="Skip writing the WeChat API draft manifest.",
    )
    parser.add_argument(
        "--publisher-config",
        type=Path,
        help="Local publisher config path. Defaults to ~/.codex/wechat-article-pipeline/publisher-config.json.",
    )
    parser.add_argument(
        "--publisher-env-file",
        type=Path,
        help="Local .env file with WECHAT_AUTHOR and WECHAT_PREVIEW_ACCOUNT defaults.",
    )
    parser.add_argument(
        "--publisher-account",
        help="Official Account selector for publisher defaults. Matches WECHAT_ACCOUNT_<ALIAS>_NAME first, then <ALIAS>.",
    )
    parser.add_argument("--author", help="Author override for the publish manifest.")
    parser.add_argument("--preview-account", help="Preview WeChat account override for the publish manifest.")
    parser.add_argument(
        "--remember-publisher-config",
        action="store_true",
        help="Persist provided author/preview values into the local publisher config.",
    )
    return parser.parse_args()


def extract_title(markdown: str, fallback: str) -> str:
    match = TITLE_RE.search(markdown)
    if match:
        return match.group(1).strip()
    return fallback


def slugify(value: str, fallback: str = "wechat-article") -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return slug or fallback


def make_path_name(value: str, fallback: str = "wechat-article") -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", value.strip(), flags=re.UNICODE)
    cleaned = re.sub(r"-+", "-", cleaned).strip("-_")
    return cleaned or fallback


def make_storage_slug(value: str, fallback: str = "wechat-article") -> str:
    slug = slugify(value, "")
    if slug:
        return slug
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return f"{fallback}-{digest}"


def file_digest(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_content_storage_key(page_title: str, markdown: str, visuals: dict[str, dict]) -> str:
    digest = hashlib.sha1()
    digest.update(page_title.encode("utf-8"))
    digest.update(markdown.encode("utf-8"))
    for name in sorted(visuals):
        digest.update(name.encode("utf-8"))
        path_value = visuals[name].get("path")
        if path_value:
            digest.update(file_digest(Path(path_value)).encode("ascii"))
    return f"wechat-md-workbench-{WORKBENCH_STORAGE_VERSION}-{make_storage_slug(page_title)}-{digest.hexdigest()[:10]}"



def infer_image_dir_name(article_path: Path, plan: dict | None) -> str:
    plan_slug = str((plan or {}).get("article_slug", "")).strip()
    if plan_slug:
        return make_path_name(plan_slug)
    stem = article_path.stem.strip()
    if stem and stem.lower() != "article":
        return make_path_name(stem)
    parent = article_path.parent.name.strip()
    if parent:
        return make_path_name(parent)
    return make_path_name(stem or article_path.name)


def infer_article_slug(article_path: Path, plan: dict | None, metadata: dict | None) -> str:
    metadata_slug = str((metadata or {}).get("slug", "")).strip()
    if metadata_slug:
        return make_path_name(metadata_slug)
    return infer_image_dir_name(article_path, plan)


def find_placeholders(markdown: str) -> list[str]:
    names = sorted({match.group(1) for match in builder.PLACEHOLDER_RE.finditer(markdown)})
    if not names:
        raise SystemExit("Article markdown does not contain any {{visual:name}} placeholders")
    return names


def find_image(images_dir: Path, name: str) -> Path:
    matches = sorted(
        path
        for path in images_dir.iterdir()
        if path.is_file() and path.stem == name and path.suffix.lower() in IMAGE_SUFFIXES
    )
    if not matches:
        supported = ", ".join(sorted(IMAGE_SUFFIXES))
        raise SystemExit(
            f"Missing image for placeholder '{name}' in {images_dir}. "
            f"Expected a file named {name}<ext> where <ext> is one of: {supported}"
        )
    if len(matches) > 1:
        joined = ", ".join(str(path) for path in matches)
        raise SystemExit(f"Multiple image files match placeholder '{name}': {joined}")
    return matches[0].resolve()


def image_size_with_sips(path: Path) -> tuple[int, int]:
    proc = subprocess.run(
        ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    width = height = 0
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("pixelWidth:"):
            width = int(line.split(":", 1)[1].strip())
        elif line.startswith("pixelHeight:"):
            height = int(line.split(":", 1)[1].strip())
    if width <= 0 or height <= 0:
        raise RuntimeError(f"Could not read image size for {path}")
    return width, height


def format_crop_value(values: tuple[float, float, float, float]) -> str:
    return "_".join(f"{max(0.0, min(1.0, value)):.6f}".rstrip("0").rstrip(".") for value in values)


def cover_crop_box(width: int, height: int, target_ratio: float) -> tuple[int, int, int, int]:
    aspect = width / height
    if aspect > target_ratio:
        crop_width = max(1, int(round(height * target_ratio)))
        left = max(0, (width - crop_width) // 2)
        return left, 0, crop_width, height
    crop_height = max(1, int(round(width / target_ratio)))
    top = max(0, (height - crop_height) // 2)
    return 0, top, width, crop_height


def crop_value_from_box(box: tuple[int, int, int, int], width: int, height: int) -> str:
    left, top, crop_width, crop_height = box
    return format_crop_value(
        (
            left / width,
            top / height,
            (left + crop_width) / width,
            (top + crop_height) / height,
        )
    )


def write_center_crop_with_sips(source: Path, out: Path, box: tuple[int, int, int, int], target_width: int, target_height: int) -> None:
    _left, _top, crop_width, crop_height = box
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="wechat-cover-crop-", suffix=source.suffix or ".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        subprocess.run(
            ["sips", "-c", str(crop_height), str(crop_width), str(source), "--out", str(tmp_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["sips", "-z", str(target_height), str(target_width), str(tmp_path), "--out", str(out)],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        tmp_path.unlink(missing_ok=True)


def build_wechat_cover_crops(images_dir: Path, cover_path: Path) -> dict[str, dict[str, str]]:
    width, height = image_size_with_sips(cover_path)
    crops: dict[str, dict[str, str]] = {}
    for name, spec in WECHAT_COVER_TARGETS.items():
        box = cover_crop_box(width, height, float(spec["ratio"]))
        out = images_dir / str(spec["filename"])
        write_center_crop_with_sips(cover_path, out, box, int(spec["width"]), int(spec["height"]))
        crops[name] = {
            "path": str(out.resolve()),
            "crop": crop_value_from_box(box, width, height),
            "source_path": str(cover_path.resolve()),
            "source_width": str(width),
            "source_height": str(height),
            "width": str(spec["width"]),
            "height": str(spec["height"]),
        }
    return crops


def read_plan(path: Path | None) -> dict | None:
    if not path:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def plan_slot_map(plan: dict | None) -> dict[str, dict]:
    if not plan:
        return {}
    slots = plan.get("image_slots") or plan.get("jobs") or []
    result: dict[str, dict] = {}
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        name = str(slot.get("name", "")).strip()
        if name:
            result[name] = slot
    return result


def build_job(
    markdown: str,
    images_dir: Path,
    plan: dict | None,
    article_metadata: dict | None,
    page_title: str,
    storage_key: str,
    brand_title: str,
    brand_subtitle: str,
    theme_color: str,
) -> dict:
    slot_map = plan_slot_map(plan)
    visuals = {
        name: {
            "path": str(find_image(images_dir, name)),
            **{
                key: slot_map[name][key]
                for key in ("role", "image_type", "source_context", "target_effect", "content_focus")
                if name in slot_map and key in slot_map[name]
            },
        }
        for name in find_placeholders(markdown)
    }
    wechat_cover_crops = {}
    if "cover" in visuals:
        wechat_cover_crops = build_wechat_cover_crops(images_dir, Path(visuals["cover"]["path"]))
    job = {
        "page_title": page_title,
        "storage_key": storage_key,
        "brand_title": brand_title,
        "brand_subtitle": brand_subtitle,
        "theme_color": theme_color,
        "article_metadata": article_metadata or {},
        "article_markdown": markdown,
        "visuals": visuals,
        "wechat_cover": {
            "source_visual": "cover",
            "source_path": visuals.get("cover", {}).get("path", ""),
            "crops": wechat_cover_crops,
        },
    }
    if plan:
        job["image_plan"] = plan.get("image_plan") or {
            "article_title": plan.get("article_title"),
            "article_summary": plan.get("article_summary"),
            "article_type": plan.get("article_type"),
            "global_visual_style": plan.get("global_visual_style"),
            "image_slots": plan.get("image_slots") or plan.get("jobs") or [],
        }
        if plan.get("image_plan_markdown"):
            job["image_plan_markdown"] = plan["image_plan_markdown"]
    return job


def render_html(job: dict, job_path: Path, out_path: Path, template_path: Path, support_dir: Path | None) -> None:
    template = template_path.read_text(encoding="utf-8")
    job_dir = job_path.parent.resolve()

    markdown = job["article_markdown"]
    rendered_visuals: dict[str, str] = {}
    quality_report: dict[str, object] = {"visuals": {}}

    for name, visual_spec in job.get("visuals", {}).items():
        asset_uri, audit = builder.resolve_image_asset(visual_spec, job_dir)
        rendered_visuals[name] = asset_uri
        quality_report["visuals"][name] = audit

    markdown, missing = builder.replace_visual_placeholders(markdown, rendered_visuals)
    if missing:
        names = ", ".join(sorted(set(missing)))
        raise SystemExit(f"Missing visual assets for placeholders: {names}")

    html = builder.apply_template(job, template, markdown)
    validate_embedded_html(html, len(rendered_visuals))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    if support_dir:
        rendered_job = dict(job)
        rendered_job["article_markdown"] = markdown
        builder.write_support_files(
            support_dir,
            job_path,
            markdown,
            rendered_visuals,
            rendered_job,
            quality_report,
        )


def write_publish_manifest(
    job_path: Path,
    out_path: Path,
    workbench_html: Path,
    article_slug: str,
    config_path: Path | None,
    env_file: Path | None,
    account: str | None,
    author: str | None,
    preview_account: str | None,
    remember: bool,
) -> None:
    command = [
        sys.executable,
        str(MAKE_PUBLISH_MANIFEST),
        str(job_path),
        str(out_path),
        "--workbench-html",
        str(workbench_html),
        "--article-slug",
        article_slug,
    ]
    if config_path:
        command.extend(["--config", str(config_path.expanduser())])
    if env_file:
        command.extend(["--env-file", str(env_file.expanduser())])
    if account:
        command.extend(["--account", account])
    if author:
        command.extend(["--author", author])
    if preview_account:
        command.extend(["--preview-account", preview_account])
    if remember:
        command.append("--remember")
    subprocess.run(command, check=True)


def default_publish_manifest_path(out_path: Path) -> Path:
    return out_path.resolve().with_suffix(".publish-manifest.json")


def validate_embedded_html(html: str, expected_visual_count: int) -> None:
    if "{{visual:" in html:
        raise SystemExit("Generated HTML still contains unresolved {{visual:*}} placeholders")
    embedded_count = html.count("data:image/")
    if embedded_count < expected_visual_count:
        raise SystemExit(
            f"Generated HTML only contains {embedded_count} embedded images; "
            f"expected at least {expected_visual_count}"
        )
    local_image_re = re.compile(
        r"!\[[^\]]*\]\((?:/Users/|file:|\.{0,2}/)[^)]+\.(?:png|jpe?g|webp|gif)\)",
        re.I,
    )
    if local_image_re.search(html):
        raise SystemExit("Generated HTML still contains markdown image links to local files")


def main() -> None:
    args = parse_args()
    source_markdown = args.article.read_text(encoding="utf-8")
    markdown, article_metadata = builder.split_front_matter(source_markdown)
    plan = read_plan(args.plan_json.resolve() if args.plan_json else None)

    metadata_title = str(article_metadata.get("title", "")).strip()
    page_title = args.page_title or extract_title(markdown, metadata_title or args.article.stem)
    image_dir_name = infer_article_slug(args.article.resolve(), plan, article_metadata)
    slug_source = image_dir_name or args.article.stem or page_title
    images_dir = (args.images_dir or (DEFAULT_IMAGE_ROOT / image_dir_name)).resolve()
    if not images_dir.exists() or not images_dir.is_dir():
        raise SystemExit(f"Images directory does not exist: {images_dir}")

    brand_title = args.brand_title or f"{page_title}工作台"
    job_out = (args.job_out or args.out.with_suffix(".job.json")).resolve()

    job = build_job(
        markdown=markdown,
        images_dir=images_dir,
        plan=plan,
        article_metadata=article_metadata,
        page_title=page_title,
        storage_key=args.storage_key or "pending-content-hash",
        brand_title=brand_title,
        brand_subtitle=args.brand_subtitle,
        theme_color=args.theme_color,
    )
    job["storage_key"] = args.storage_key or make_content_storage_key(page_title or slug_source, markdown, job["visuals"])

    job_out.parent.mkdir(parents=True, exist_ok=True)
    job_out.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

    render_html(
        job=job,
        job_path=job_out,
        out_path=args.out.resolve(),
        template_path=args.template.resolve(),
        support_dir=args.support_dir.resolve() if args.support_dir else None,
    )

    if not args.no_publish_manifest:
        manifest_out = (args.publish_manifest_out or default_publish_manifest_path(args.out)).resolve()
        write_publish_manifest(
            job_path=job_out,
            out_path=manifest_out,
            workbench_html=args.out.resolve(),
            article_slug=slug_source,
            config_path=args.publisher_config,
            env_file=args.publisher_env_file,
            account=args.publisher_account,
            author=args.author,
            preview_account=args.preview_account,
            remember=args.remember_publisher_config,
        )

    print(f"Wrote {job_out}")
    print(f"Wrote {args.out.resolve()}")
    if not args.no_publish_manifest:
        print(f"Wrote {(args.publish_manifest_out or default_publish_manifest_path(args.out)).resolve()}")
    if args.support_dir:
        print(f"Wrote support files to {args.support_dir.resolve()}")


if __name__ == "__main__":
    main()
