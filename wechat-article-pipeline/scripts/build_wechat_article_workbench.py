#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import html
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote_to_bytes


DEFAULT_TEMPLATE = Path(__file__).resolve().parents[1] / "assets" / "templates" / "wechat-md-workbench.template.v3.html"
PLACEHOLDER_RE = re.compile(r"\{\{visual:([a-zA-Z0-9_-]+)\}\}")
BOOTSTRAP_RE = re.compile(r'<script[^>]+id=["\']wechat-bootstrap["\'][^>]*>(.*?)</script>', re.S | re.I)
FRONT_MATTER_RE = re.compile(r"\A---[ \t]*\n(?P<body>.*?)[ \t]*\n---[ \t]*(?:\n|$)", re.S)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build an editable WeChat article workbench HTML with relative local image references."
    )
    parser.add_argument("job", type=Path, help="Path to the article job JSON.")
    parser.add_argument("out", type=Path, help="Path to the output HTML file.")
    parser.add_argument(
        "--template",
        type=Path,
        default=DEFAULT_TEMPLATE,
        help="Path to the base workbench template HTML.",
    )
    parser.add_argument(
        "--support-dir",
        type=Path,
        help="Optional directory for writing source markdown, job JSON, support assets, and quality reports.",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def html_safe_json(value: Any) -> str:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))

def read_bootstrap(html_text: str) -> dict[str, Any]:
    matches = BOOTSTRAP_RE.findall(html_text)
    if len(matches) == 1: return json.loads(matches[0])
    def grab(pattern, default):
        m = re.search(pattern, html_text, re.S)
        return json.loads(m.group(1)) if m else default
    return {"markdown": grab(r"const DEFAULT_MARKDOWN = `([\s\S]*?)`;", ""), "metadata": grab(r"const ARTICLE_METADATA = (.*?);", {}), "signature": grab(r"const ARTICLE_SIGNATURE = (.*?);", {}), "storageKey": grab(r"const STORAGE_KEY = (.*?);", "wechat-md-workbench-generated"), "workbenchState": grab(r"const DEFAULT_WORKBENCH_STATE = (.*?);", {})}

def replace_bootstrap(html_text: str, updates: dict[str, Any]) -> str:
    matches = list(BOOTSTRAP_RE.finditer(html_text))
    if len(matches) > 1: raise ValueError("duplicate wechat-bootstrap nodes")
    if len(matches) == 1:
        current = json.loads(matches[0].group(1)); current.update(updates)
        return html_text[:matches[0].start(1)] + html_safe_json(current) + html_text[matches[0].end(1):]
    return html_text


def escape_for_js_template(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("${", "\\${")
        .replace("</script>", "<\\/script>")
    )


def parse_front_matter(raw: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            metadata[key] = value
    return metadata


def split_front_matter(markdown: str) -> tuple[str, dict[str, Any]]:
    match = FRONT_MATTER_RE.match(markdown)
    if not match:
        return markdown, {}
    raw = match.group("body").strip()
    body = markdown[match.end() :].lstrip("\n")
    return body, {"raw": raw, **parse_front_matter(raw)}


def ensure_data_uri(payload: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def infer_mime_type(path: Path, fallback: str = "image/png") -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or fallback


def extension_for_mime_type(mime_type: str) -> str:
    normalized = mime_type.lower().split(";", 1)[0].strip()
    return {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/bmp": ".bmp",
        "image/svg+xml": ".svg",
    }.get(normalized, ".png")


def safe_asset_name(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-")
    return cleaned or "image"


def decode_data_uri(data_uri: str) -> tuple[bytes, str]:
    if not data_uri.startswith("data:") or "," not in data_uri:
        raise ValueError("Invalid data URI")
    header, payload = data_uri.split(",", 1)
    mime_type = header[5:].split(";", 1)[0] or "image/png"
    if ";base64" in header:
        return base64.b64decode(payload), mime_type
    return unquote_to_bytes(payload), mime_type


def materialized_assets_dir(out_path: Path) -> Path:
    return out_path.with_name(f"{out_path.stem}.assets")


def materialize_data_uri(data_uri: str, asset_name: str, out_dir: Path) -> Path:
    payload, mime_type = decode_data_uri(data_uri)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{safe_asset_name(asset_name)}{extension_for_mime_type(mime_type)}"
    out.write_bytes(payload)
    return out


def resolve_image_asset(spec: dict[str, Any], job_dir: Path) -> tuple[str, dict[str, Any]]:
    source = "unknown"
    mime_type = spec.get("mime_type")

    if "data_uri" in spec:
        return spec["data_uri"], {"source": "data_uri", "embedded": True}

    if "base64" in spec:
        if not mime_type:
            raise SystemExit("Image asset with base64 payload requires mime_type")
        payload = base64.b64decode(spec["base64"])
        return ensure_data_uri(payload, mime_type), {"source": "base64", "embedded": True}

    if "path" in spec:
        raw_path = Path(spec["path"])
        path = raw_path if raw_path.is_absolute() else (job_dir / raw_path).resolve()
        if not path.exists():
            raise SystemExit(f"Image asset path does not exist: {path}")
        source = "path"
        payload = path.read_bytes()
        return ensure_data_uri(payload, mime_type or infer_mime_type(path)), {
            "source": source,
            "embedded": True,
            "path": str(path),
        }

    if "url" in spec:
        return spec["url"], {"source": "url", "embedded": False}

    raise SystemExit("Each visual asset must provide one of: data_uri, base64, path, url")


def resolve_image_reference(
    spec: dict[str, Any],
    job_dir: Path,
    reference_dir: Path,
    asset_name: str = "image",
    generated_assets_dir: Path | None = None,
) -> tuple[str, dict[str, Any]]:
    if "path" in spec:
        raw_path = Path(spec["path"])
        path = raw_path if raw_path.is_absolute() else (job_dir / raw_path).resolve()
        if not path.exists():
            raise SystemExit(f"Image asset path does not exist: {path}")

        relative_path = os.path.relpath(path, start=reference_dir.resolve())
        return Path(relative_path).as_posix(), {
            "source": "path",
            "embedded": False,
            "path": str(path),
            "reference_dir": str(reference_dir.resolve()),
        }

    asset_uri, audit = resolve_image_asset(spec, job_dir)
    if asset_uri.startswith("data:image/") and generated_assets_dir:
        path = materialize_data_uri(asset_uri, asset_name, generated_assets_dir)
        relative_path = os.path.relpath(path, start=reference_dir.resolve())
        return Path(relative_path).as_posix(), {
            **audit,
            "embedded": False,
            "materialized": True,
            "path": str(path),
            "reference_dir": str(reference_dir.resolve()),
        }
    return asset_uri, audit


def replace_default_markdown(template: str, markdown: str) -> str:
    escaped = escape_for_js_template(markdown)
    return re.sub(
        r"const DEFAULT_MARKDOWN = `.*?`;",
        lambda _match: f"const DEFAULT_MARKDOWN = `{escaped}`;",
        template,
        flags=re.S,
    )


def replace_default_metadata(template: str, metadata: dict[str, Any]) -> str:
    payload = json.dumps(metadata, ensure_ascii=False)
    return re.sub(
        r"const ARTICLE_METADATA = .*?;",
        lambda _match: f"const ARTICLE_METADATA = {payload};",
        template,
        flags=re.S,
    )


def replace_article_signature(template: str, signature: dict[str, Any]) -> str:
    payload = json.dumps(signature, ensure_ascii=False)
    return re.sub(
        r"const ARTICLE_SIGNATURE = .*?;",
        lambda _match: f"const ARTICLE_SIGNATURE = {payload};",
        template,
        flags=re.S,
    )


def replace_default_workbench_state(template: str, state: dict[str, str]) -> str:
    payload = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    return re.sub(
        r"const DEFAULT_WORKBENCH_STATE = .*?;",
        lambda _match: f"const DEFAULT_WORKBENCH_STATE = {payload};",
        template,
        flags=re.S,
    )


def replace_clipboard_assets_script(template: str, script_path: str) -> str:
    if script_path:
        tag = f'<script src="{html.escape(script_path, quote=True)}"></script>'
    else:
        tag = ""
    return template.replace("<!-- CLIPBOARD_ASSETS_SCRIPT -->", tag)


def replace_first(pattern: str, repl: str, text: str) -> str:
    return re.sub(pattern, repl, text, count=1, flags=re.S)


def apply_template(job: dict[str, Any], template: str, markdown: str) -> str:
    markdown, markdown_metadata = split_front_matter(markdown)
    article_metadata = job.get("article_metadata") or markdown_metadata
    page_title = str(job.get("page_title", "公众号 Markdown 工作台"))
    storage_key = str(job.get("storage_key", "wechat-md-workbench-generated"))
    brand_title = str(job.get("brand_title", "公众号 Markdown 工作台"))
    brand_subtitle = str(job.get("brand_subtitle", "HTML 工作台 · 相对路径配图 · 可继续编辑"))
    theme_color = str(job.get("theme_color", "#17b394"))

    html_text = template
    html_text = replace_first(r"<title>.*?</title>", f"<title>{html.escape(page_title)}</title>", html_text)
    html_text = replace_first(r'<div class="brand-title">.*?</div>', f'<div class="brand-title">{html.escape(brand_title)}</div>', html_text)
    html_text = replace_first(r'<div class="brand-sub">.*?</div>', f'<div class="brand-sub">{html.escape(brand_subtitle)}</div>', html_text)
    html_text = replace_first(r'(<input id="themeColor"[^>]*value=")[^"]+(")', rf"\g<1>{html.escape(theme_color, quote=True)}\2", html_text)
    html_text = replace_first(r"const STORAGE_KEY = .*?;", f"const STORAGE_KEY = {json.dumps(storage_key, ensure_ascii=False)};", html_text)
    state = {
            "themeColor": theme_color,
            "fontSize": str(job.get("font_size", "16")),
            "fontFamily": str(
                job.get(
                    "font_family",
                    '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif',
                )
            ),
        }
    bootstrap = {"markdown": markdown, "metadata": article_metadata if isinstance(article_metadata, dict) else {}, "signature": job.get("article_signature") or {}, "storageKey": storage_key, "workbenchState": state}
    if html_text.count("{{BOOTSTRAP_JSON}}") != 1: raise ValueError("expected exactly one {{BOOTSTRAP_JSON}} placeholder")
    html_text = html_text.replace("{{BOOTSTRAP_JSON}}", html_safe_json(bootstrap), 1)
    controller_path = Path(__file__).resolve().parents[1] / "assets" / "workbench-save-controller.js"
    controller_source = controller_path.read_text(encoding="utf-8")
    if html_text.count("{{SAVE_CONTROLLER_JS}}") != 1: raise ValueError("expected exactly one {{SAVE_CONTROLLER_JS}} placeholder")
    html_text = html_text.replace("{{SAVE_CONTROLLER_JS}}", controller_source, 1)
    html_text = replace_clipboard_assets_script(html_text, str(job.get("clipboard_assets_script", "")).strip())
    return html_text


def write_support_files(
    support_dir: Path,
    job_path: Path,
    markdown: str,
    resolved_assets: dict[str, str],
    rendered_job: dict[str, Any],
    quality_report: dict[str, Any],
) -> None:
    support_dir.mkdir(parents=True, exist_ok=True)
    (support_dir / "article.md").write_text(markdown, encoding="utf-8")
    (support_dir / "job.rendered.json").write_text(
        json.dumps(rendered_job, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (support_dir / "job.source.json").write_text(job_path.read_text(encoding="utf-8"), encoding="utf-8")
    (support_dir / "quality-report.json").write_text(
        json.dumps(quality_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (support_dir / "resolved-assets.json").write_text(
        json.dumps(resolved_assets, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if rendered_job.get("image_plan"):
        (support_dir / "image-plan.json").write_text(
            json.dumps(rendered_job["image_plan"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if rendered_job.get("image_plan_markdown"):
        (support_dir / "image-plan.md").write_text(
            str(rendered_job["image_plan_markdown"]),
            encoding="utf-8",
        )


def clipboard_assets_path(out_path: Path) -> Path:
    return out_path.with_name(f"{out_path.stem}.clipboard-assets.js")


def write_clipboard_assets(
    out_path: Path,
    rendered_visuals: dict[str, str],
    visuals: dict[str, Any],
    job_dir: Path,
) -> str:
    assets: dict[str, str] = {}
    for name, visual_spec in visuals.items():
        reference = rendered_visuals.get(name, "")
        if not reference or reference.startswith("data:image/") or not isinstance(visual_spec, dict):
            continue
        try:
            data_uri, _audit = resolve_image_asset(visual_spec, job_dir)
        except Exception:
            continue
        if data_uri.startswith("data:image/"):
            assets[reference] = data_uri
    if not assets:
        return ""
    out = clipboard_assets_path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "window.WECHAT_CLIPBOARD_IMAGE_DATA = "
        + json.dumps(assets, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    return Path(os.path.relpath(out.resolve(), start=out_path.resolve().parent)).as_posix()


def replace_visual_placeholders(markdown: str, rendered_visuals: dict[str, str]) -> tuple[str, list[str]]:
    missing: list[str] = []

    # First replace the canonical markdown-image form: ![alt]({{visual:name}}).
    image_placeholder_re = re.compile(r"!\[([^\]]*)\]\(\s*\{\{visual:([a-zA-Z0-9_-]+)\}\}\s*\)")

    def image_repl(match: re.Match[str]) -> str:
        alt = match.group(1) or match.group(2)
        name = match.group(2)
        value = rendered_visuals.get(name)
        if value is None:
            missing.append(name)
            return match.group(0)
        return f"![{alt}]({value})"

    markdown = image_placeholder_re.sub(image_repl, markdown)

    # Then replace any remaining bare {{visual:name}} with a full markdown image.
    def bare_repl(match: re.Match[str]) -> str:
        name = match.group(1)
        value = rendered_visuals.get(name)
        if value is None:
            missing.append(name)
            return match.group(0)
        return f"![{name}]({value})"

    return PLACEHOLDER_RE.sub(bare_repl, markdown), missing


def main() -> None:
    args = parse_args()
    job = read_json(args.job)
    template = args.template.read_text(encoding="utf-8")
    job_dir = args.job.parent.resolve()

    markdown, article_metadata = split_front_matter(job["article_markdown"])
    if article_metadata and not job.get("article_metadata"):
        job["article_metadata"] = article_metadata
    visuals = job.get("visuals", {})
    rendered_visuals: dict[str, str] = {}
    quality_report: dict[str, Any] = {"visuals": {}}

    for name, visual_spec in visuals.items():
        asset_uri, audit = resolve_image_reference(
            visual_spec,
            job_dir,
            args.out.resolve().parent,
            name,
            materialized_assets_dir(args.out.resolve()),
        )
        rendered_visuals[name] = asset_uri
        quality_report["visuals"][name] = audit

    markdown, missing = replace_visual_placeholders(markdown, rendered_visuals)
    if missing:
        names = ", ".join(sorted(set(missing)))
        raise SystemExit(f"Missing visual assets for placeholders: {names}")

    clipboard_assets_script = write_clipboard_assets(args.out.resolve(), rendered_visuals, visuals, job_dir)
    if clipboard_assets_script:
        job["clipboard_assets_script"] = clipboard_assets_script
    html = apply_template(job, template, markdown)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")

    if args.support_dir:
        rendered_job = dict(job)
        rendered_job["article_markdown"] = markdown
        write_support_files(
            args.support_dir,
            args.job,
            markdown,
            rendered_visuals,
            rendered_job,
            quality_report,
        )

    print(f"Wrote {args.out}")
    if args.support_dir:
        print(f"Wrote support files to {args.support_dir}")
        print(f"Wrote quality report to {args.support_dir / 'quality-report.json'}")


if __name__ == "__main__":
    main()
