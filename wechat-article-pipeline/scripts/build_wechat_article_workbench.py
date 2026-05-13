#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import html
import json
import mimetypes
import re
from pathlib import Path
from typing import Any


DEFAULT_TEMPLATE = Path(__file__).resolve().parents[1] / "assets" / "templates" / "wechat-md-workbench.template.html"
PLACEHOLDER_RE = re.compile(r"\{\{visual:([a-zA-Z0-9_-]+)\}\}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a single-file editable WeChat article workbench HTML."
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


def escape_for_js_template(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("${", "\\${")
        .replace("</script>", "<\\/script>")
    )


def ensure_data_uri(payload: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def infer_mime_type(path: Path, fallback: str = "image/png") -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or fallback


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


def replace_default_markdown(template: str, markdown: str) -> str:
    escaped = escape_for_js_template(markdown)
    return re.sub(
        r"const DEFAULT_MARKDOWN = `.*?`;",
        f"const DEFAULT_MARKDOWN = `{escaped}`;",
        template,
        flags=re.S,
    )


def replace_first(pattern: str, repl: str, text: str) -> str:
    return re.sub(pattern, repl, text, count=1, flags=re.S)


def apply_template(job: dict[str, Any], template: str, markdown: str) -> str:
    page_title = str(job.get("page_title", "公众号 Markdown 工作台"))
    storage_key = str(job.get("storage_key", "wechat-md-workbench-generated"))
    brand_title = str(job.get("brand_title", "公众号 Markdown 工作台"))
    brand_subtitle = str(job.get("brand_subtitle", "单文件 HTML · 含正文和配图 · 可继续编辑"))
    theme_color = str(job.get("theme_color", "#17b394"))

    html_text = template
    html_text = replace_first(r"<title>.*?</title>", f"<title>{html.escape(page_title)}</title>", html_text)
    html_text = replace_first(r'<div class="brand-title">.*?</div>', f'<div class="brand-title">{html.escape(brand_title)}</div>', html_text)
    html_text = replace_first(r'<div class="brand-sub">.*?</div>', f'<div class="brand-sub">{html.escape(brand_subtitle)}</div>', html_text)
    html_text = replace_first(r'(<input id="themeColor"[^>]*value=")[^"]+(")', rf"\g<1>{html.escape(theme_color, quote=True)}\2", html_text)
    html_text = replace_first(r"const STORAGE_KEY = .*?;", f"const STORAGE_KEY = {json.dumps(storage_key, ensure_ascii=False)};", html_text)
    html_text = replace_default_markdown(html_text, markdown)
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

    markdown = job["article_markdown"]
    visuals = job.get("visuals", {})
    rendered_visuals: dict[str, str] = {}
    quality_report: dict[str, Any] = {"visuals": {}}

    for name, visual_spec in visuals.items():
        asset_uri, audit = resolve_image_asset(visual_spec, job_dir)
        rendered_visuals[name] = asset_uri
        quality_report["visuals"][name] = audit

    markdown, missing = replace_visual_placeholders(markdown, rendered_visuals)
    if missing:
        names = ", ".join(sorted(set(missing)))
        raise SystemExit(f"Missing visual assets for placeholders: {names}")

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
