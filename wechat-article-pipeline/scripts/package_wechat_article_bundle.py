#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

import build_wechat_article_workbench as builder
import release_info
import wechat_account_config as account_config
from article_core import extract_title
from atomic_files import atomic_write_text
from image_jobs_contract import normalize_image_jobs, derive_image_plan, render_image_plan_markdown


WORKSPACE = Path.cwd()
DEFAULT_IMAGE_ROOT = WORKSPACE / "image"
DEFAULT_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
MAKE_PUBLISH_MANIFEST = Path(__file__).resolve().parent / "make_wechat_publish_manifest.py"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
PLANNED_VISUAL_IMAGE_RE = re.compile(
    r"!\[[^\]]*\]\(\s*\{\{visual:([a-zA-Z0-9_-]+)\}\}\s*\)"
)
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
        "--no-images",
        action="store_true",
        help="Allow packaging markdown without {{visual:*}} placeholders or local image files.",
    )
    parser.add_argument(
        "--cover-image",
        type=Path,
        help=(
            "Explicit cover image for WeChat draft manifests when --no-images is used. "
            "The cover is uploaded as thumb_media_id but is not inserted into the article body."
        ),
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
        default="HTML 工作台 · 相对路径配图 · 可继续编辑",
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
    manifest_group = parser.add_mutually_exclusive_group()
    manifest_group.add_argument(
        "--publish-manifest",
        action="store_true",
        help="Also write a WeChat API draft manifest. Local workbench packaging skips it by default.",
    )
    manifest_group.add_argument(
        "--no-publish-manifest",
        action="store_true",
        help="Deprecated compatibility flag; local packaging already skips the publish manifest by default.",
    )
    parser.add_argument(
        "--publisher-config",
        type=Path,
        help="Local publisher config path. Defaults to ~/.codex/wechat-article-pipeline/publisher-config.json.",
    )
    parser.add_argument(
        "--publisher-env-file",
        type=Path,
        help=(
            "Local .env file with publisher defaults and display signature fields. "
            "Defaults to the skill repo .env if present."
        ),
    )
    parser.add_argument(
        "--publisher-account",
        help="Official Account selector for publisher defaults. Matches WECHAT_ACCOUNT_<ALIAS>_NAME first, then <ALIAS>.",
    )
    parser.add_argument("--author", help="Author override for the publish manifest.")
    parser.add_argument("--preview-account", help="Preview WeChat account override for the publish manifest.")
    parser.add_argument("--signature-author", help="Visible article signature author shown below the cover image.")
    parser.add_argument("--original-issue", type=int, help="Visible original article issue number shown below the cover image.")
    parser.add_argument(
        "--no-increment-original-issue",
        action="store_true",
        help="Deprecated compatibility flag. Packaging no longer increments original issue by default.",
    )
    parser.add_argument(
        "--increment-original-issue",
        action="store_true",
        help="Explicitly advance the selected account's WECHAT_ORIGINAL_ISSUE after packaging.",
    )
    parser.add_argument(
        "--remember-publisher-config",
        action="store_true",
        help="Persist provided author/preview values into the local publisher config.",
    )
    return parser.parse_args()


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
    plan_slug = str(((plan or {}).get("article") or {}).get("slug", "")).strip()
    if not plan_slug:
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


def find_slot_image(images_dir: Path, name: str, slot: dict | None) -> Path:
    output = str((slot or {}).get("output", "")).strip()
    if not output:
        return find_image(images_dir, name)
    candidate = (images_dir / output).resolve()
    if not candidate.is_file():
        raise SystemExit(
            f"Missing planned image for slot '{name}': {candidate}. "
            "Generate the exact slots[].output file before packaging."
        )
    return candidate


def resolve_cover_image(path: Path) -> Path:
    cover = path.expanduser().resolve()
    if not cover.exists() or not cover.is_file():
        raise SystemExit(f"Cover image does not exist: {cover}")
    if cover.suffix.lower() not in IMAGE_SUFFIXES:
        supported = ", ".join(sorted(IMAGE_SUFFIXES))
        raise SystemExit(f"Cover image must be one of: {supported}")
    return cover


def image_size_from_header(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        return struct.unpack("<HH", data[6:10])
    if data.startswith(b"\xff\xd8"):
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            index += 2
            if marker in (0xD8, 0xD9):
                continue
            if index + 2 > len(data):
                break
            segment_length = int.from_bytes(data[index : index + 2], "big")
            if segment_length < 2:
                break
            if marker in {
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            } and index + 7 <= len(data):
                height = int.from_bytes(data[index + 3 : index + 5], "big")
                width = int.from_bytes(data[index + 5 : index + 7], "big")
                return width, height
            index += segment_length
    raise RuntimeError(f"Could not read image size from file header for {path}")


def image_size_with_pillow(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as img:
        return img.size


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


def image_size(path: Path) -> tuple[int, int]:
    try:
        return image_size_from_header(path)
    except Exception:
        pass
    try:
        return image_size_with_pillow(path)
    except Exception:
        return image_size_with_sips(path)


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


def write_center_crop_with_pillow(source: Path, out: Path, box: tuple[int, int, int, int], target_width: int, target_height: int) -> None:
    from PIL import Image

    left, top, crop_width, crop_height = box
    out.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as img:
        resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        cropped = img.crop((left, top, left + crop_width, top + crop_height))
        cropped.resize((target_width, target_height), resampling).save(out)


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


def write_center_crop(source: Path, out: Path, box: tuple[int, int, int, int], target_width: int, target_height: int) -> None:
    try:
        write_center_crop_with_pillow(source, out, box, target_width, target_height)
    except (ImportError, ModuleNotFoundError):
        write_center_crop_with_sips(source, out, box, target_width, target_height)


def build_wechat_cover_crops(images_dir: Path, cover_path: Path) -> dict[str, dict[str, str]]:
    width, height = image_size(cover_path)
    crops: dict[str, dict[str, str]] = {}
    for name, spec in WECHAT_COVER_TARGETS.items():
        box = cover_crop_box(width, height, float(spec["ratio"]))
        out = images_dir / str(spec["filename"])
        write_center_crop(cover_path, out, box, int(spec["width"]), int(spec["height"]))
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


def remove_visual_placeholders(markdown: str, names: set[str]) -> str:
    if not names:
        return markdown
    markdown = PLANNED_VISUAL_IMAGE_RE.sub(
        lambda match: "" if match.group(1) in names else match.group(0),
        markdown,
    )
    for name in names:
        markdown = markdown.replace(f"{{{{visual:{name}}}}}", "")
    return re.sub(r"\n{3,}", "\n\n", markdown).strip() + "\n"


def remove_intentionally_skipped_visuals(markdown: str, plan: dict | None) -> str:
    if not plan:
        return markdown
    article = plan.get("article", {})
    skipped = article.get("skipped_visuals", []) if isinstance(article, dict) else []
    return remove_visual_placeholders(markdown, set(skipped))


def signature_issue_key(account: dict[str, str]) -> str:
    alias = account.get("alias", "").strip()
    return f"WECHAT_ACCOUNT_{alias}_ORIGINAL_ISSUE" if alias else "WECHAT_ORIGINAL_ISSUE"


def resolve_signature_metadata(
    env_file: Path,
    account: dict[str, str],
    signature_author: str | None,
    original_issue: int | None,
) -> dict[str, object]:
    author = (signature_author or account.get("signature_author") or "").strip()
    raw_issue = str(original_issue if original_issue is not None else account.get("original_issue", "")).strip()
    try:
        issue = int(raw_issue) if raw_issue else 1
    except ValueError:
        raise SystemExit(f"Invalid original issue value in {env_file}: {raw_issue!r}. Use a positive integer.")
    if issue < 1:
        raise SystemExit("Original issue must be a positive integer.")
    return {
        "author": author,
        "issue": issue,
        "label": f"{author}的第{issue}篇原创" if author else "",
        "env_file": str(env_file.expanduser()),
        "account": {
            "alias": account.get("alias", ""),
            "name": account.get("name", ""),
        },
        "issue_env_key": signature_issue_key(account),
    }


def plan_slot_map(plan: dict | None) -> dict[str, dict]:
    if not plan:
        return {}
    slots = plan.get("slots") or plan.get("image_slots") or plan.get("jobs") or []
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
    article_signature: dict[str, object] | None,
    allow_no_images: bool = False,
    cover_image: Path | None = None,
) -> dict:
    slot_map = plan_slot_map(plan)
    placeholder_names = sorted({match.group(1) for match in builder.PLACEHOLDER_RE.finditer(markdown)})
    if not placeholder_names and allow_no_images:
        visuals = {}
        if cover_image:
            visuals["cover"] = {
                "path": str(resolve_cover_image(cover_image)),
                "role": "api_cover",
                "image_type": "cover_asset",
                "source_context": "Explicit cover for WeChat draft delivery; not inserted into the article body.",
            }
    else:
        if not placeholder_names:
            raise SystemExit("Article markdown does not contain any {{visual:name}} placeholders")
        visuals = {
            name: {
                "path": str(find_slot_image(images_dir, name, slot_map.get(name))),
                **{
                    key: slot_map[name][key]
                    for key in ("role", "image_type", "source_context", "target_effect", "content_focus")
                    if name in slot_map and key in slot_map[name]
                },
            }
            for name in placeholder_names
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
        "article_signature": article_signature or {},
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
        try:
            canonical = normalize_image_jobs(plan)
            job["image_plan"] = derive_image_plan(canonical)
            job["image_plan_markdown"] = render_image_plan_markdown(canonical)
        except ValueError as exc:
            raise SystemExit(f"Invalid image jobs: {exc}")
    return job


def render_html(job: dict, job_path: Path, out_path: Path, template_path: Path, support_dir: Path | None) -> None:
    template = template_path.read_text(encoding="utf-8")
    job_dir = job_path.parent.resolve()

    markdown = job["article_markdown"]
    expected_visual_count = len({match.group(1) for match in builder.PLACEHOLDER_RE.finditer(markdown)})
    rendered_visuals: dict[str, str] = {}
    quality_report: dict[str, object] = {"visuals": {}}

    for name, visual_spec in job.get("visuals", {}).items():
        asset_uri, audit = builder.resolve_image_reference(
            visual_spec,
            job_dir,
            out_path.resolve().parent,
            name,
            builder.materialized_assets_dir(out_path.resolve()),
        )
        rendered_visuals[name] = asset_uri
        quality_report["visuals"][name] = audit

    markdown, missing = builder.replace_visual_placeholders(markdown, rendered_visuals)
    if missing:
        names = ", ".join(sorted(set(missing)))
        raise SystemExit(f"Missing visual assets for placeholders: {names}")

    clipboard_assets_script = builder.write_clipboard_assets(
        out_path.resolve(),
        rendered_visuals,
        job.get("visuals", {}),
        job_dir,
    )
    if clipboard_assets_script:
        job["clipboard_assets_script"] = clipboard_assets_script
    platform_image_urls, platform_image_source = builder.discover_platform_image_urls(job, job_path)
    html = builder.apply_template(
        job,
        template,
        markdown,
        platform_image_urls=platform_image_urls,
        platform_image_source=platform_image_source,
        build_info=release_info.workbench_build_info(template_path),
        platform_adapters=release_info.platform_adapters(),
    )
    validate_workbench_html(html, expected_visual_count)

    atomic_write_text(out_path, html)

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


def validate_workbench_html(html: str, expected_visual_count: int) -> None:
    if "{{visual:" in html:
        raise SystemExit("Generated HTML still contains unresolved {{visual:*}} placeholders")
    if expected_visual_count and html.count("![") < expected_visual_count:
        raise SystemExit(
            f"Generated HTML only contains {html.count('![')} markdown image links; "
            f"expected at least {expected_visual_count}"
        )
    nonportable_image_re = re.compile(r"!\[[^\]]*\]\((?:file:|/)[^)]+\.(?:png|jpe?g|webp|gif|bmp|svg)\)", re.I)
    if nonportable_image_re.search(html):
        raise SystemExit("Generated HTML contains non-portable absolute local image paths")


def main() -> None:
    args = parse_args()
    if args.increment_original_issue and args.no_increment_original_issue:
        raise SystemExit(
            "--increment-original-issue and --no-increment-original-issue cannot be used together."
        )
    if args.publish_manifest_out and args.no_publish_manifest:
        raise SystemExit("--publish-manifest-out cannot be combined with --no-publish-manifest.")
    publish_manifest = bool(args.publish_manifest or args.publish_manifest_out)
    if args.no_images and publish_manifest and not args.cover_image:
        raise SystemExit(
            "WeChat draft publishing requires a cover image even when --no-images is used. "
            "Pass --cover-image <path> or omit --publish-manifest for local formatting only."
        )

    source_markdown = args.article.read_text(encoding="utf-8")
    markdown, article_metadata = builder.split_front_matter(source_markdown)
    plan = read_plan(args.plan_json.resolve() if args.plan_json else None)
    if plan is not None:
        try:
            plan = normalize_image_jobs(plan)
        except ValueError as exc:
            raise SystemExit(f"Invalid image jobs: {exc}") from exc
        markdown = remove_intentionally_skipped_visuals(markdown, plan)
    if args.no_images:
        markdown = remove_visual_placeholders(
            markdown,
            {match.group(1) for match in builder.PLACEHOLDER_RE.finditer(markdown)},
        )
    env_file = (args.publisher_env_file or DEFAULT_ENV_FILE).expanduser()
    publisher_env = account_config.read_env_file(env_file)
    signature_account = account_config.find_account_profile(
        publisher_env,
        args.publisher_account,
        include_signature=not (
            args.signature_author is not None and args.original_issue is not None
        ),
    )
    article_signature = resolve_signature_metadata(
        env_file=env_file,
        account=signature_account,
        signature_author=args.signature_author,
        original_issue=args.original_issue,
    )

    metadata_title = str(article_metadata.get("title", "")).strip()
    page_title = args.page_title or extract_title(markdown, metadata_title or args.article.stem)
    image_dir_name = infer_article_slug(args.article.resolve(), plan, article_metadata)
    slug_source = image_dir_name or args.article.stem or page_title
    images_dir = (args.images_dir or (DEFAULT_IMAGE_ROOT / image_dir_name)).resolve()
    has_visual_placeholders = bool(builder.PLACEHOLDER_RE.search(markdown))
    if (has_visual_placeholders or not args.no_images) and (not images_dir.exists() or not images_dir.is_dir()):
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
        article_signature=article_signature,
        allow_no_images=args.no_images,
        cover_image=args.cover_image,
    )
    job["storage_key"] = args.storage_key or make_content_storage_key(page_title or slug_source, markdown, job["visuals"])

    atomic_write_text(job_out, json.dumps(job, ensure_ascii=False, indent=2) + "\n")

    render_html(
        job=job,
        job_path=job_out,
        out_path=args.out.resolve(),
        template_path=args.template.resolve(),
        support_dir=args.support_dir.resolve() if args.support_dir else None,
    )

    if publish_manifest:
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

    # Keep this compatibility option after every requested artifact has been
    # produced successfully, so a failed manifest build never advances issue.
    if (
        article_signature.get("author")
        and args.original_issue is None
        and args.increment_original_issue
        and not args.no_increment_original_issue
    ):
        try:
            account_config.compare_and_set_env_value(
                env_file,
                str(article_signature["issue_env_key"]),
                str(article_signature["issue"]),
                str(int(article_signature["issue"]) + 1),
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc

    print(f"Wrote {job_out}")
    print(f"Wrote {args.out.resolve()}")
    if publish_manifest:
        print(f"Wrote {(args.publish_manifest_out or default_publish_manifest_path(args.out)).resolve()}")
    if args.support_dir:
        print(f"Wrote support files to {args.support_dir.resolve()}")


if __name__ == "__main__":
    main()
