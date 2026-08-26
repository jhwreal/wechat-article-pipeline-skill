#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any

import build_wechat_article_workbench as builder
import wechat_account_config as account_config
from article_core import extract_title
from atomic_files import atomic_write_json


DEFAULT_CONFIG = Path.home() / ".codex" / "wechat-article-pipeline" / "publisher-config.json"
DEFAULT_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
DEFAULT_TOKEN_CACHE = Path.home() / ".codex" / "wechat-article-pipeline" / "wechat-token-cache.json"
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
BASE_TEXT_STYLE = "font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;font-size:16px;line-height:1.75;color:#222;word-break:break-word"
PARAGRAPH_STYLE = BASE_TEXT_STYLE + ";margin:16px 8px"
IMAGE_PARAGRAPH_STYLE = BASE_TEXT_STYLE + ";margin:22px 8px;text-align:center"
IMAGE_STYLE = "max-width:100%;display:block;margin:0 auto;border-radius:8px"
STRONG_STYLE = "font-weight:700;color:#17b394"
ACCENT_STYLE = "color:#d14d72;font-weight:700"
LINK_STYLE = "color:#17b394;text-decoration:none;border-bottom:1px solid rgba(23,179,148,.35)"
CODE_STYLE = "background:#f2f4f7;border:1px solid #eaecf0;border-radius:6px;padding:.12em .38em;font-size:.92em;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:#d14d72;font-weight:700"
CODE_BLOCK_STYLE = "font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:14px;line-height:1.7;color:#e5e7eb;background:#111827;border-radius:10px;margin:16px 8px;padding:14px 16px;box-sizing:border-box;word-break:break-word;overflow-wrap:anywhere"
TABLE_STYLE = "width:100%;border-collapse:collapse;table-layout:fixed;margin:18px 0;border:1px solid #dfe3e8"
TABLE_HEADER_STYLE = "padding:8px 4px;border:1px solid #dfe3e8;background:#f7f8fa;color:#111827;font-size:13px;line-height:1.5;font-weight:700;vertical-align:middle;word-break:break-word"
TABLE_CELL_STYLE = "padding:8px 4px;border:1px solid #dfe3e8;color:#222;font-size:13px;line-height:1.5;vertical-align:middle;word-break:break-word"
SIGNATURE_STYLE = BASE_TEXT_STYLE + ";margin:21px 8px;color:#fff;font-size:14px;line-height:1.45;font-weight:400;text-align:center"
SIGNATURE_TEXT_STYLE = "display:inline;padding:1px 5px 2px;background:#17b394;color:#fff;font-size:14px;line-height:1.45;font-weight:400"
DATA_IMAGE_PREFIX = "data:image/"


def is_data_image_uri(value: str) -> bool:
    return value[: len(DATA_IMAGE_PREFIX)].lower() == DATA_IMAGE_PREFIX


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a WeChat Official Account publishing manifest from a rendered article job."
    )
    parser.add_argument("job", type=Path, help="Rendered or source job JSON from package_wechat_article_bundle.py.")
    parser.add_argument("out", type=Path, help="Path to write <html-stem>.publish-manifest.json.")
    parser.add_argument("--workbench-html", type=Path, help="Path to the generated HTML workbench.")
    parser.add_argument("--article-slug", help="Optional article slug override.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Local publisher config path.")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE, help="Local .env with publisher defaults.")
    parser.add_argument(
        "--account",
        help=(
            "Official Account selector for publisher defaults. Matches WECHAT_ACCOUNT_<ALIAS>_NAME first, then <ALIAS>."
        ),
    )
    parser.add_argument("--author", help="Author override. Also used for this manifest without persisting.")
    parser.add_argument("--preview-account", help="Preview WeChat account override without persisting.")
    parser.add_argument(
        "--source-state-json",
        help="Internal workbench source-state JSON to embed without a second manifest rewrite.",
    )
    parser.add_argument("--remember", action="store_true", help="Persist provided author/preview values to config.")
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_source_state_json(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        source_state = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid --source-state-json: {exc}") from exc
    if not isinstance(source_state, dict):
        raise SystemExit("--source-state-json must decode to a JSON object.")
    return source_state


def read_config(path: Path) -> dict[str, str]:
    if not path.exists():
        return {"author": "", "preview_account": ""}
    data = read_json(path)
    return {
        "author": str(data.get("author", "")).strip(),
        "preview_account": str(data.get("preview_account", "")).strip(),
    }


def write_config(path: Path, config: dict[str, str]) -> None:
    atomic_write_json(path, config, mode=0o600)


def author_env_key(account: dict[str, str]) -> str:
    alias = account.get("alias", "").strip()
    return f"WECHAT_ACCOUNT_{alias}_AUTHOR" if alias else "WECHAT_AUTHOR"


def resolve_author(args: argparse.Namespace, env_file: Path, account: dict[str, str]) -> str:
    if args.author is not None:
        author = args.author.strip()
        if not author:
            raise SystemExit("Author is empty. Provide a non-empty --author value.")
        if args.remember:
            account_config.write_env_value(env_file, author_env_key(account), author)
        return author
    if account.get("author"):
        return account["author"].strip()
    key = author_env_key(account)
    selector = account.get("selector") or account.get("name") or account.get("alias") or "default account"
    raise SystemExit(
        f"Missing WeChat article author for {selector}. Ask the user for the author, then store it in {env_file} as {key}=<author>."
    )


def strip_markdown(text: str) -> str:
    text = IMAGE_RE.sub("", text)
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"==([^=\n]+)==", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.M)
    text = re.sub(r"^\s{0,3}>\s?", "", text, flags=re.M)
    text = re.sub(r"^\s{0,3}[-*+]\s+", "", text, flags=re.M)
    text = re.sub(r"^\s{0,3}\d+[.)]\s+", "", text, flags=re.M)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_digest(markdown: str, title: str, limit: int = 120) -> str:
    blocks = [strip_markdown(block) for block in re.split(r"\n\s*\n", markdown)]
    for block in blocks:
        if block and block != title:
            return block[:limit]
    return ""


def markdown_for_draft_body(markdown: str, title: str) -> str:
    match = re.match(
        r"^(?P<prefix>(?:\s*!\[[^\]]*\]\([^)]+\)\s*)*)#\s+(?P<title>[^\n]+)\s*(?:\n+|$)",
        markdown,
    )
    if not match:
        return markdown
    if strip_markdown(match.group("title")) != title.strip():
        return markdown
    prefix = match.group("prefix").strip()
    body = markdown[match.end() :].lstrip("\n")
    if not prefix:
        return body
    return f"{prefix}\n\n{body}"


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


def validate_publish_image_sources(markdown: str, cover: dict[str, str]) -> None:
    for match in IMAGE_RE.finditer(markdown):
        source = match.group(2).strip()
        if not is_data_image_uri(source):
            raise SystemExit(
                "Publish manifest body images must resolve to embedded data:image URIs; "
                f"unsupported source: {source!r}. Use a local path/data URI or omit publish-manifest generation."
            )
    cover_source = str(cover.get("src", "")).strip()
    if cover_source and not is_data_image_uri(cover_source):
        raise SystemExit(
            "Publish manifest cover must resolve to an embedded data:image URI; "
            f"unsupported source: {cover_source!r}."
        )


def compute_source_fingerprint(
    job: dict[str, Any],
    job_dir: Path,
    rendered_visuals: dict[str, str] | None = None,
) -> str:
    canonical_job = json.loads(json.dumps(job, ensure_ascii=False))
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
    return digest.hexdigest()


def visual_candidate(name: str, spec: Any, job_dir: Path, alt: str) -> dict[str, str]:
    if not isinstance(spec, dict):
        return {}
    src, _audit = builder.resolve_image_asset(spec, job_dir)
    return {"name": name, "alt": alt, "src": src}


def select_cover_candidate(
    markdown: str,
    visuals: dict[str, Any],
    job_dir: Path,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    candidates = image_candidates(markdown, visuals)
    cover = next((item for item in candidates if item["name"] == "cover"), {})
    if cover:
        return cover, candidates

    explicit_cover = visual_candidate("cover", visuals.get("cover"), job_dir, "题图")
    if explicit_cover:
        candidates.insert(0, explicit_cover)
        return explicit_cover, candidates

    return (candidates[0] if candidates else {}), candidates


def build_wechat_cover_manifest(job: dict[str, Any], cover: dict[str, str], job_dir: Path) -> dict[str, Any]:
    source = job.get("wechat_cover") if isinstance(job.get("wechat_cover"), dict) else {}
    crops = source.get("crops") if isinstance(source.get("crops"), dict) else {}
    crop_previews: dict[str, dict[str, str]] = {}
    crop_values: dict[str, str] = {}
    for name, spec in crops.items():
        if not isinstance(spec, dict):
            continue
        crop = str(spec.get("crop", "")).strip()
        if crop:
            crop_values[str(name)] = crop
        path = str(spec.get("path", "")).strip()
        if path:
            try:
                asset_uri, _audit = builder.resolve_image_asset({"path": path}, job_dir)
            except Exception:
                asset_uri = ""
            crop_previews[str(name)] = {
                "src": asset_uri,
                "path": path,
                "width": str(spec.get("width", "")),
                "height": str(spec.get("height", "")),
                "crop": crop,
            }
    return {
        "source_visual": str(source.get("source_visual", "cover")),
        "src": cover.get("src", ""),
        "alt": cover.get("alt", ""),
        "crop_values": crop_values,
        "crop_previews": crop_previews,
    }


def inline_format(text: str) -> str:
    escaped = html.escape(text, quote=True)
    code_spans: list[str] = []

    def code_token(index: int) -> str:
        return f"\x00INLINE_CODE_{index}\x00"

    def protect_code(match: re.Match[str]) -> str:
        code_spans.append(f'<code style="{CODE_STYLE}">{match.group(1)}</code>')
        return code_token(len(code_spans) - 1)

    escaped = re.sub(r"`([^`]+)`", protect_code, escaped)
    def safe_url(value: str, *, image: bool) -> bool:
        candidate = html.unescape(value).strip()
        scheme_probe = re.sub(r"[\x00-\x20\x7f]+", "", candidate).lower()
        scheme_match = re.match(r"^([a-z][a-z0-9+.-]*):", scheme_probe)
        if not scheme_match:
            return True
        scheme = scheme_match.group(1)
        if scheme in {"http", "https"}:
            return True
        if not image and scheme == "mailto":
            return True
        return image and scheme == "data" and scheme_probe.startswith("data:image/")

    def replace_image(match: re.Match[str]) -> str:
        alt, url = match.groups()
        if not safe_url(url, image=True):
            return alt
        return f'<img alt="{alt}" src="{url}" style="{IMAGE_STYLE}" />'

    def replace_link(match: re.Match[str]) -> str:
        label, url = match.groups()
        if not safe_url(url, image=False):
            return label
        return f'<a href="{url}" style="{LINK_STYLE}">{label}</a>'

    escaped = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replace_image, escaped)
    escaped = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace_link, escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", rf'<strong style="{STRONG_STYLE}">\1</strong>', escaped)
    escaped = re.sub(r"==([^=\n]+)==", rf'<span style="{ACCENT_STYLE}">\1</span>', escaped)
    escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)
    for index, value in enumerate(code_spans):
        escaped = escaped.replace(code_token(index), value)
    return escaped


def image_paragraph(alt: str, src: str) -> str:
    return f'<p style="{IMAGE_PARAGRAPH_STYLE}"><img alt="{html.escape(alt, quote=True)}" src="{html.escape(src, quote=True)}" style="{IMAGE_STYLE}" /></p>'


def paragraph(content: str, style: str = PARAGRAPH_STYLE) -> str:
    return f'<p style="{style}">{content}</p>'


def format_text_lines(lines: list[str]) -> str:
    return "<br>".join(inline_format(line.strip()) for line in lines)


def markdown_table_html(block: str) -> str | None:
    lines = [line.strip() for line in block.strip().splitlines() if line.strip()]
    if len(lines) < 2:
        return None

    raw_rows = [
        line.removeprefix("|").removesuffix("|").split("|")
        for line in lines
    ]
    delimiters = [cell.strip() for cell in raw_rows[1]]
    looks_like_table = (
        "|" in lines[0]
        and "|" in lines[1]
        and bool(delimiters)
        and all(re.fullmatch(r":?-{3,}:?", cell) for cell in delimiters)
    )
    if not looks_like_table:
        return None

    expected_columns = len(raw_rows[0])
    malformed_row_index = next(
        (
            index
            for index, row in enumerate(raw_rows[1:], start=2)
            if len(row) != expected_columns
        ),
        None,
    )
    if expected_columns == 0 or malformed_row_index is not None:
        offending_index = malformed_row_index or 1
        offending_row = lines[offending_index - 1]
        raise SystemExit(
            "Malformed Markdown table in the WeChat publish body: "
            f"row {offending_index} has "
            f"{len(raw_rows[offending_index - 1])} columns; expected {expected_columns}. "
            f"Offending row: {offending_row!r}. "
            "Do not wrap a whole row as **| ... |**; bold the individual cell contents instead, "
            "for example: | **label** | **value** |. Draft creation is blocked until the table is fixed."
        )

    alignments: list[str] = []
    for delimiter in delimiters:
        if delimiter.startswith(":") and delimiter.endswith(":"):
            alignments.append("center")
        elif delimiter.endswith(":"):
            alignments.append("right")
        else:
            alignments.append("left")

    def render_row(cells: list[str], tag: str, base_style: str) -> str:
        rendered: list[str] = []
        for index, cell in enumerate(cells):
            style = f"{base_style};text-align:{alignments[index]}"
            rendered.append(f'<{tag} style="{style}">{inline_format(cell.strip())}</{tag}>')
        return "<tr>" + "".join(rendered) + "</tr>"

    header = render_row(raw_rows[0], "th", TABLE_HEADER_STYLE)
    body = "".join(render_row(row, "td", TABLE_CELL_STYLE) for row in raw_rows[2:])
    return f'<table style="{TABLE_STYLE}"><thead>{header}</thead><tbody>{body}</tbody></table>'


def split_markdown_blocks(markdown: str) -> list[str]:
    blocks: list[str] = []
    normal_lines: list[str] = []
    code_lines: list[str] = []
    in_code = False

    def flush_normal() -> None:
        if normal_lines:
            block = "\n".join(normal_lines).strip()
            if block:
                blocks.append(block)
            normal_lines.clear()

    for line in markdown.splitlines():
        if in_code:
            code_lines.append(line)
            if re.match(r"^```\s*$", line):
                blocks.append("\n".join(code_lines))
                code_lines.clear()
                in_code = False
            continue

        if re.match(r"^```", line):
            flush_normal()
            code_lines = [line]
            in_code = True
            continue

        if not line.strip():
            flush_normal()
            continue

        normal_lines.append(line)

    if in_code and code_lines:
        blocks.append("\n".join(code_lines))
    flush_normal()
    return blocks


def markdown_to_wechat_html(markdown: str) -> str:
    color = "#17b394"
    blocks = split_markdown_blocks(markdown)
    html_blocks: list[str] = []
    for block in blocks:
        table_html = markdown_table_html(block)
        if table_html:
            html_blocks.append(table_html)
            continue
        image_only = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", block.strip())
        if image_only:
            html_blocks.append(image_paragraph(image_only.group(1).strip(), image_only.group(2).strip()))
            continue
        if block.startswith("```"):
            code = re.sub(r"^```[^\n]*\n?", "", block)
            code = re.sub(r"\n?```\s*$", "", code)
            lines = [
                html.escape(line).replace(" ", "&nbsp;") or "&nbsp;"
                for line in code.rstrip("\n").split("\n")
            ]
            html_blocks.append(paragraph("<br>".join(lines), CODE_BLOCK_STYLE))
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", block)
        if heading:
            level = len(heading.group(1))
            text = inline_format(heading.group(2))
            if level == 1:
                style = BASE_TEXT_STYLE + f";margin:26px 8px 16px;font-size:19px;line-height:1.75;font-weight:700;color:#111827;padding-bottom:8px;border-bottom:2px solid {color};text-align:center"
            elif level == 2:
                outer_style = BASE_TEXT_STYLE + ";margin:30px 8px 18px;text-align:center"
                badge_style = f"display:inline-block;max-width:100%;box-sizing:border-box;font-size:19px;line-height:1.6;font-weight:700;color:#fff;background:{color};padding:8px 20px;border-radius:7px;box-shadow:0 4px 10px rgba(15,23,42,.16);text-align:center"
                html_blocks.append(paragraph(f'<span style="{badge_style}">{text}</span>', outer_style))
                continue
            elif level == 3:
                style = BASE_TEXT_STYLE + f";margin:24px 8px 14px;font-size:17px;line-height:1.75;font-weight:700;color:#111827;padding:0 0 3px 10px;border-left:4px solid {color};border-bottom:1px dashed {color}"
            else:
                style = BASE_TEXT_STYLE + f";margin:18px 8px 10px;font-size:16px;line-height:1.75;font-weight:700;color:{color}"
            html_blocks.append(paragraph(text, style))
            continue
        if block.startswith(">"):
            quote = "<br>".join(inline_format(line.lstrip("> ").strip()) for line in block.splitlines())
            style = BASE_TEXT_STYLE + f";margin:18px 8px;padding:14px 16px;background:#f7f8fa;border-left:4px solid {color};color:#3b4552;font-size:16px;line-height:1.75;border-radius:8px"
            html_blocks.append(paragraph(quote, style))
            continue
        if re.match(r"^[-*+]\s+", block):
            items = [
                "• " + inline_format(re.sub(r"^[-*+]\s+", "", line).strip())
                for line in block.splitlines()
                if re.match(r"^[-*+]\s+", line)
            ]
            html_blocks.append(paragraph("<br>".join(items)))
            continue
        if re.match(r"^\d+\.\s+", block):
            items = [
                inline_format(line.strip())
                for line in block.splitlines()
                if re.match(r"^\d+\.\s+", line)
            ]
            html_blocks.append(paragraph("<br>".join(items)))
            continue
        html_blocks.append(paragraph(format_text_lines(block.splitlines())))

    return "".join(html_blocks)


def signature_label(job: dict[str, Any]) -> str:
    signature = job.get("article_signature") if isinstance(job.get("article_signature"), dict) else {}
    author = str(signature.get("author", "")).strip()
    issue = str(signature.get("issue", "")).strip()
    return f"{author}的第{issue}篇原创" if author and issue else ""


def inject_signature_html(content_html: str, label: str) -> str:
    if not label:
        return content_html
    signature_html = (
        f'<p style="{SIGNATURE_STYLE}">'
        f'<span style="{SIGNATURE_TEXT_STYLE}">{html.escape(label)}</span>'
        "</p>"
    )
    return re.sub(r"(<p\b[^>]*>\s*<img\b[^>]*>\s*</p>)", r"\1" + signature_html, content_html, count=1, flags=re.I)


def main() -> None:
    args = parse_args()
    job = read_json(args.job.resolve())
    config = read_config(args.config.expanduser())
    env = account_config.read_env_file(args.env_file)
    account = account_config.find_account_profile(env, args.account, include_credentials=True)
    if account.get("preview_account"):
        config["preview_account"] = account["preview_account"]

    overrides = {
        "preview_account": args.preview_account,
    }
    for key, value in overrides.items():
        if value is not None:
            config[key] = value.strip()
    author = resolve_author(args, args.env_file, account)

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
    draft_markdown = markdown_for_draft_body(markdown, title)
    visuals = job.get("visuals", {}) if isinstance(job.get("visuals"), dict) else {}
    cover, candidates = select_cover_candidate(markdown, visuals, args.job.resolve().parent)
    validate_publish_image_sources(markdown, cover)
    wechat_cover = build_wechat_cover_manifest(job, cover, args.job.resolve().parent)
    article_slug = args.article_slug or str(job.get("article_slug", "")).strip() or args.job.stem
    account_manifest = {
        "selector": account.get("selector", ""),
        "alias": account.get("alias", ""),
        "name": account.get("name", ""),
    }
    preview_manifest = {
        "method": "message/mass/preview",
        "account": config.get("preview_account", ""),
    }
    env_file_manifest = str(args.env_file.expanduser())

    content_html = inject_signature_html(
        markdown_to_wechat_html(draft_markdown),
        signature_label(job),
    )
    manifest = {
        "schema_version": 1,
        "workbench_refresh": {
            "article_slug": article_slug,
            "author": author,
            "env_file": env_file_manifest,
            "account": account_manifest,
            "preview": {"account": preview_manifest["account"]},
        },
        "article_slug": article_slug,
        "title": title,
        "author": author,
        "digest": extract_digest(markdown, title),
        "content_html": content_html,
        "content_text": strip_markdown(draft_markdown),
        "source_fingerprint": compute_source_fingerprint(
            job,
            args.job.resolve().parent,
            rendered_visuals,
        ),
        "workbench_html": str(args.workbench_html.resolve()) if args.workbench_html else "",
        "article_signature": job.get("article_signature", {}) if isinstance(job.get("article_signature"), dict) else {},
        "account": account_manifest,
        "cover": cover,
        "wechat_cover": wechat_cover,
        "image_candidates": candidates,
        "comment": {
            "need_open_comment": 1,
            "only_fans_can_comment": 0,
            "scope": "all",
            "auto_elect": False,
            "auto_elect_note": "The draft/add API can open comments for everyone, but it does not expose an automatic selected-comments switch.",
        },
        "unsupported_by_draft_api": {
            "original_declaration": "Not present in the official draft/add article fields.",
            "reward": "Not present in the official draft/add article fields.",
            "auto_selected_comments": "The official mark-elect comment API requires a published msg_data_id and a concrete user_comment_id, so it cannot be configured at draft creation.",
        },
        "preview": preview_manifest,
        "env_file": env_file_manifest,
        "token_cache_path": str(account_config.account_token_cache_path(DEFAULT_TOKEN_CACHE, account)),
        "safety": {
            "use_official_api_only": True,
            "avoid_computer_use_on_mp_backend": True,
            "never_click_publish": True,
            "never_call_publish_api_by_default": True,
        },
    }

    source_state = parse_source_state_json(args.source_state_json)
    if source_state is not None:
        manifest["source_state"] = source_state
    atomic_write_json(args.out, manifest)
    print(f"Wrote {args.out.resolve()}")


if __name__ == "__main__":
    main()
