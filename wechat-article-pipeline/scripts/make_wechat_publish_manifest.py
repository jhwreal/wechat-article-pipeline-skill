#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any

import build_wechat_article_workbench as builder


DEFAULT_CONFIG = Path.home() / ".codex" / "wechat-article-pipeline" / "publisher-config.json"
DEFAULT_API_CONFIG = Path.home() / ".codex" / "wechat-article-pipeline" / "wechat-api-config.json"
TITLE_RE = re.compile(r"^\s*#\s+(.+?)\s*$", re.M)
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a WeChat Official Account publishing manifest from a rendered article job."
    )
    parser.add_argument("job", type=Path, help="Rendered or source job JSON from package_wechat_article_bundle.py.")
    parser.add_argument("out", type=Path, help="Path to write publish-manifest.json.")
    parser.add_argument("--workbench-html", type=Path, help="Path to the generated HTML workbench.")
    parser.add_argument("--article-slug", help="Optional article slug override.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Local publisher config path.")
    parser.add_argument("--author", help="Author override. Also used for this manifest without persisting.")
    parser.add_argument("--preview-account", help="Preview WeChat account override without persisting.")
    parser.add_argument("--remember", action="store_true", help="Persist provided author/preview values to config.")
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_config(path: Path) -> dict[str, str]:
    if not path.exists():
        return {"author": "", "preview_account": ""}
    data = read_json(path)
    return {
        "author": str(data.get("author", "")).strip(),
        "preview_account": str(data.get("preview_account", "")).strip(),
    }


def write_config(path: Path, config: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def extract_title(markdown: str, fallback: str) -> str:
    match = TITLE_RE.search(markdown)
    return match.group(1).strip() if match else fallback


def strip_markdown(text: str) -> str:
    text = IMAGE_RE.sub("", text)
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    text = re.sub(r"^[#>\-\*\+\d\.\s]+", "", text, flags=re.M)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_digest(markdown: str, title: str, limit: int = 120) -> str:
    blocks = [strip_markdown(block) for block in re.split(r"\n\s*\n", markdown)]
    for block in blocks:
        if block and block != title:
            return block[:limit]
    return ""


def image_candidates(markdown: str, visuals: dict[str, Any]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in IMAGE_RE.finditer(markdown):
        alt = match.group(1).strip()
        src = match.group(2).strip()
        name = ""
        for visual_name, spec in visuals.items():
            if isinstance(spec, dict) and str(spec.get("path", "")).strip() == src:
                name = visual_name
                break
        if not name:
            if "cover" in alt.lower() or "题图" in alt:
                name = "cover"
            elif "尾图" in alt:
                name = "closing"
            else:
                name = f"image-{len(candidates) + 1}"
        key = f"{name}:{src}"
        if key in seen:
            continue
        seen.add(key)
        candidates.append({"name": name, "alt": alt, "src": src})
    return candidates


def inline_format(text: str) -> str:
    escaped = html.escape(text, quote=True)
    escaped = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img alt="\1" src="\2" />', escaped)
    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)
    return escaped


def markdown_to_wechat_html(markdown: str) -> str:
    color = "#17b394"
    blocks = [block.strip() for block in re.split(r"\n\s*\n", markdown) if block.strip()]
    html_blocks: list[str] = []
    for block in blocks:
        if block.startswith("```"):
            code = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", block).removesuffix("```")
            lines = [
                f'<span style="display:block;min-height:1.7em;margin:0;padding:0;background:transparent;color:#e5e7eb;font-size:14px;line-height:1.7;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;word-break:break-word;overflow-wrap:anywhere">{html.escape(line).replace(" ", "&nbsp;") or "&nbsp;"}</span>'
                for line in code.rstrip("\n").split("\n")
            ]
            html_blocks.append(
                '<section style="display:block;width:100%;max-width:100%;box-sizing:border-box;margin:18px 0;padding:14px 16px;background:#111827;color:#e5e7eb;border-radius:10px;font-size:14px;line-height:1.7;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;word-break:break-word;overflow-wrap:anywhere">'
                + "".join(lines)
                + "</section>"
            )
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", block)
        if heading:
            level = len(heading.group(1))
            text = inline_format(heading.group(2))
            if level == 1:
                style = f"width:fit-content;margin:26px auto 16px;font-size:19px;line-height:1.75;font-weight:700;color:#111827;padding-bottom:8px;border-bottom:2px solid {color};text-align:center"
                html_blocks.append(f'<h1 style="{style}">{text}</h1>')
            elif level == 2:
                style = f"width:fit-content;margin:30px auto 18px;font-size:19px;line-height:1.6;font-weight:700;color:#fff;background:{color};padding:8px 20px;border-radius:7px;box-shadow:0 8px 16px rgba(23,179,148,.22),0 2px 5px rgba(15,23,42,.08);text-align:center"
                html_blocks.append(f'<h2 style="{style}">{text}</h2>')
            elif level == 3:
                style = f"width:fit-content;margin:24px 0 14px;font-size:17px;line-height:1.75;font-weight:700;color:#111827;padding:0 0 3px 10px;border-left:4px solid {color};border-bottom:1px dashed {color}"
                html_blocks.append(f'<h3 style="{style}">{text}</h3>')
            else:
                style = f"margin:18px 0 10px;font-size:16px;line-height:1.75;font-weight:700;color:{color}"
                html_blocks.append(f'<h4 style="{style}">{text}</h4>')
            continue
        if block.startswith(">"):
            quote = "<br>".join(inline_format(line.lstrip("> ").strip()) for line in block.splitlines())
            html_blocks.append(
                f'<blockquote style="margin:18px 0;padding:14px 16px;background:#f7f8fa;border-left:4px solid {color};color:#3b4552;font-size:16px;line-height:1.75;border-radius:8px"><p style="margin:0;color:inherit">{quote}</p></blockquote>'
            )
            continue
        if re.match(r"^[-*+]\s+", block):
            items = "".join(f"<li>{inline_format(line[2:].strip())}</li>" for line in block.splitlines() if len(line) > 2)
            html_blocks.append(f'<ul style="margin:16px 0;padding-left:1.5em;font-size:16px;line-height:1.75">{items}</ul>')
            continue
        paragraph = "<br>".join(inline_format(line.strip()) for line in block.splitlines())
        html_blocks.append(f'<p style="margin:16px 0;font-size:16px;line-height:1.75;color:#222">{paragraph}</p>')

    return (
        '<section style="font-family:-apple-system,BlinkMacSystemFont,\'PingFang SC\',\'Microsoft YaHei\',sans-serif;font-size:16px;line-height:1.75;color:#222;word-break:break-word">'
        '<div style="width:100%;max-width:100%;padding-left:8px;padding-right:8px;box-sizing:border-box">'
        + "".join(html_blocks)
        + "</div></section>"
    )


def main() -> None:
    args = parse_args()
    job = read_json(args.job.resolve())
    config = read_config(args.config.expanduser())

    overrides = {
        "author": args.author,
        "preview_account": args.preview_account,
    }
    for key, value in overrides.items():
        if value is not None:
            config[key] = value.strip()

    if args.remember:
        write_config(args.config.expanduser(), config)

    markdown = str(job.get("article_markdown", ""))
    rendered_visuals: dict[str, str] = {}
    for name, visual_spec in (job.get("visuals", {}) or {}).items():
        if not isinstance(visual_spec, dict):
            continue
        asset_uri, _ = builder.resolve_image_asset(visual_spec, args.job.resolve().parent)
        rendered_visuals[str(name)] = asset_uri
    if rendered_visuals:
        markdown, missing = builder.replace_visual_placeholders(markdown, rendered_visuals)
        if missing:
            names = ", ".join(sorted(set(missing)))
            raise SystemExit(f"Missing visual assets for publish manifest placeholders: {names}")

    title = extract_title(markdown, str(job.get("page_title", args.job.stem)))
    visuals = job.get("visuals", {}) if isinstance(job.get("visuals"), dict) else {}
    candidates = image_candidates(markdown, visuals)
    cover = next((item for item in candidates if item["name"] == "cover"), candidates[0] if candidates else {})
    article_slug = args.article_slug or str(job.get("article_slug", "")).strip() or args.job.stem

    manifest = {
        "schema_version": 1,
        "article_slug": article_slug,
        "title": title,
        "author": config.get("author", ""),
        "digest": extract_digest(markdown, title),
        "content_html": markdown_to_wechat_html(markdown),
        "content_text": strip_markdown(markdown),
        "workbench_html": str(args.workbench_html.resolve()) if args.workbench_html else "",
        "cover": cover,
        "image_candidates": candidates,
        "preview": {
            "method": "message/mass/preview",
            "account": config.get("preview_account", ""),
        },
        "publisher_config_path": str(args.config.expanduser()),
        "api_config_path": str(DEFAULT_API_CONFIG),
        "safety": {
            "use_official_api_only": True,
            "avoid_computer_use_on_mp_backend": True,
            "never_click_publish": True,
            "never_call_publish_api_by_default": True,
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.out.resolve()}")


if __name__ == "__main__":
    main()
