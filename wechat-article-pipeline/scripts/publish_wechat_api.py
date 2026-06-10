#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import re
import secrets
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import wechat_account_config as account_config


DEFAULT_API_CONFIG = Path.home() / ".codex" / "wechat-article-pipeline" / "wechat-api-config.json"
DEFAULT_TOKEN_CACHE = Path.home() / ".codex" / "wechat-article-pipeline" / "wechat-token-cache.json"
API_BASE = "https://api.weixin.qq.com"
DATA_IMAGE_RE = re.compile(r'src=(["\'])(data:image/[^"\']+)\1', re.I)
VISUAL_PLACEHOLDER_RE = re.compile(r"\{\{visual:[^}]+\}\}")
WECHAT_DRAFT_UNSTABLE_TAG_RE = re.compile(r"</?(section|div|blockquote|pre|ul|ol)\b", re.I)
MAX_BODY_IMAGE_BYTES = 1024 * 1024
BODY_IMAGE_TARGET_BYTES = MAX_BODY_IMAGE_BYTES - 2048
ERROR_HELP = {
    40164: "当前调用 IP 不在公众号接口 IP 白名单。把这台机器的出口 IP 加到公众平台开发配置后重试。",
    48001: "公众号没有开通或没有获得该接口权限。",
    89503: "此次调用需要管理员确认。请到微信侧完成确认后重试。",
    89506: "管理员拒绝了本 IP 的调用请求。按官方提示等待后再试。",
    89507: "管理员拒绝了本 IP 的调用请求。按官方提示等待后再试。",
}


@dataclass
class LocalImage:
    path: Path
    mime: str
    width: int = 0
    height: int = 0
    original_bytes: int = 0
    upload_bytes: int = 0
    quality: int = 0
    scale: float = 1.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a WeChat Official Account draft from a publish manifest via official APIs."
    )
    parser.add_argument("manifest", type=Path, help="<html-stem>.publish-manifest.json from package_wechat_article_bundle.py.")
    parser.add_argument("--env-file", type=Path, help="Local .env file containing WECHAT_APPID and WECHAT_APPSECRET.")
    parser.add_argument("--config", type=Path, default=DEFAULT_API_CONFIG, help="Legacy local API config path.")
    parser.add_argument("--token-cache", type=Path, default=DEFAULT_TOKEN_CACHE, help="Local access_token cache path.")
    parser.add_argument(
        "--account",
        help=(
            "Official Account selector. Matches WECHAT_ACCOUNT_<ALIAS>_NAME first, then <ALIAS>. "
            "Use this when one .env stores multiple accounts."
        ),
    )
    parser.add_argument("--appid", help="WeChat Official Account AppID. Overrides .env and legacy config.")
    parser.add_argument("--appsecret", help="WeChat Official Account AppSecret. Overrides .env and legacy config.")
    parser.add_argument("--access-token", help="Use an existing access_token instead of fetching one.")
    parser.add_argument("--force-refresh-token", action="store_true", help="Force refresh stable access_token.")
    parser.add_argument("--remember", action="store_true", help="Persist token cache. Credentials are read from .env, not written to result files.")
    parser.add_argument("--check-draft-switch", action="store_true", help="Check draft switch state before creating a draft.")
    parser.add_argument("--open-draft-switch", action="store_true", help="Open the draft switch if WeChat reports it closed.")
    parser.add_argument("--verify-draft", action="store_true", help="Fetch the created draft and verify the returned title.")
    parser.add_argument("--send-preview", action="store_true", help="Send a preview after the draft is created.")
    parser.add_argument("--preview-account", help="Preview target WeChat ID. Overrides manifest preview.account.")
    parser.add_argument("--preview-openid", help="Preview target OpenID. Takes precedence over WeChat ID.")
    parser.add_argument("--content-source-url", default="", help="Optional original/source URL for the article.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and write the draft request payload without API calls.")
    parser.add_argument("--include-payload", action="store_true", help="Include full draft payload in result JSON. This can be very large.")
    parser.add_argument(
        "--out",
        type=Path,
        help="Path to write API result JSON. Defaults to <manifest>.wechat-api-result.json.",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.expanduser().read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_config(path: Path) -> dict[str, Any]:
    path = path.expanduser()
    if not path.exists():
        return {}
    return read_json(path)


def find_env_file(manifest: Path, explicit: Path | None) -> Path | None:
    if explicit:
        return explicit.expanduser()
    candidates = [
        Path.cwd() / ".env",
        manifest.resolve().parent / ".env",
        manifest.resolve().parent.parent / ".env",
        Path(__file__).resolve().parents[1] / ".env",
        Path(__file__).resolve().parents[2] / ".env",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def save_config(path: Path, config: dict[str, Any]) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def save_token_cache(path: Path, token: str, expires_in: int) -> None:
    data = {"access_token": token, "expires_at": int(time.time()) + expires_in}
    save_config(path, data)


def api_post_json(path: str, payload: dict[str, Any], access_token: str | None = None) -> dict[str, Any]:
    query = {}
    if access_token:
        query["access_token"] = access_token
    url = make_api_url(path, query)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    return request_json(req)


def make_api_url(path: str, query: dict[str, str]) -> str:
    base_path, _, existing_query = path.partition("?")
    merged = dict(urllib.parse.parse_qsl(existing_query, keep_blank_values=True))
    merged.update(query)
    url = API_BASE + base_path
    if merged:
        url += "?" + urllib.parse.urlencode(merged)
    return url


def api_post_multipart(path: str, fields: dict[str, str], files: dict[str, LocalImage], access_token: str) -> dict[str, Any]:
    boundary = "----codex-wechat-" + secrets.token_hex(12)
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    for name, image in files.items():
        filename = image.path.name
        parts.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode(),
                f"Content-Type: {image.mime}\r\n\r\n".encode(),
                image.path.read_bytes(),
                b"\r\n",
            ]
        )
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    url = make_api_url(path, {"access_token": access_token})
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(len(body))},
        method="POST",
    )
    return request_json(req)


def request_json(req: urllib.request.Request) -> dict[str, Any]:
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=60, context=context) as resp:
            data = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        data = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"WeChat API HTTP {exc.code}: {data}") from exc
    try:
        result = json.loads(data)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"WeChat API returned non-JSON response: {data[:500]}") from exc
    errcode = result.get("errcode")
    if errcode not in (None, 0):
        help_text = ERROR_HELP.get(int(errcode), "请用官方 API 诊断工具结合 errmsg/rid 排查。")
        raise SystemExit(f"WeChat API error {errcode}: {result.get('errmsg', '')}\n{help_text}")
    return result


def get_access_token(
    args: argparse.Namespace,
    config: dict[str, Any],
    account: dict[str, str],
) -> str:
    if args.access_token:
        return args.access_token.strip()

    token_cache = read_config(args.token_cache)
    cached = token_cache or (config.get("access_token_cache") or {})
    if not args.force_refresh_token and cached.get("access_token") and float(cached.get("expires_at", 0)) > time.time() + 300:
        return str(cached["access_token"])

    appid = (args.appid or account.get("appid") or config.get("appid") or "").strip()
    appsecret = (args.appsecret or account.get("appsecret") or config.get("appsecret") or "").strip()
    if not appid or not appsecret:
        raise SystemExit(
            "Missing WeChat AppID/AppSecret. For the default account, set WECHAT_APPID/WECHAT_APPSECRET. "
            "For a named account, set WECHAT_ACCOUNT_<ALIAS>_NAME, WECHAT_ACCOUNT_<ALIAS>_APPID, "
            "and WECHAT_ACCOUNT_<ALIAS>_APPSECRET in .env. You can also pass --appid and --appsecret for one-off runs."
        )

    payload: dict[str, Any] = {"grant_type": "client_credential", "appid": appid, "secret": appsecret}
    if args.force_refresh_token:
        payload["force_refresh"] = True
    token_resp = api_post_json("/cgi-bin/stable_token", payload)
    token = str(token_resp["access_token"])
    expires_in = int(token_resp.get("expires_in", 7200))
    if args.remember:
        save_token_cache(args.token_cache, token, expires_in)
    return token


def decode_data_image(data_uri: str, suffix_hint: str) -> LocalImage:
    header, encoded = data_uri.split(",", 1)
    mime = header[5:].split(";")[0].lower()
    raw = base64.b64decode(encoded)
    suffix = mimetypes.guess_extension(mime) or f".{suffix_hint}"
    tmp = tempfile.NamedTemporaryFile(prefix="wechat-image-", suffix=suffix, delete=False)
    tmp.write(raw)
    tmp.close()
    width = height = 0
    try:
        from PIL import Image

        with Image.open(tmp.name) as img:
            width, height = img.size
    except Exception:
        try:
            width, height = image_size_with_sips(Path(tmp.name))
        except Exception:
            pass
    size = Path(tmp.name).stat().st_size
    return LocalImage(Path(tmp.name), mime, width, height, original_bytes=size, upload_bytes=size)


def cleanup_temp_image(image: LocalImage | None) -> None:
    if not image:
        return
    try:
        image.path.unlink(missing_ok=True)
    except OSError:
        pass


def normalize_body_image(image: LocalImage) -> LocalImage:
    allowed = {"image/jpeg", "image/png"}
    original_size = image.path.stat().st_size
    image.original_bytes = image.original_bytes or original_size
    image.upload_bytes = original_size
    if image.mime in allowed and original_size <= MAX_BODY_IMAGE_BYTES:
        return image
    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover - optional dependency
        return normalize_body_image_with_sips(image, exc)

    def save_candidate(img: Any, quality: int, candidate_paths: list[Path]) -> tuple[Path, int]:
        out = tempfile.NamedTemporaryFile(prefix="wechat-body-", suffix=".jpg", delete=False)
        out.close()
        img.save(out.name, "JPEG", quality=quality, optimize=True, progressive=True)
        path = Path(out.name)
        candidate_paths.append(path)
        return path, path.stat().st_size

    def best_quality_under_limit(img: Any) -> tuple[Path, int, int] | None:
        candidate_paths: list[Path] = []
        best: tuple[Path, int, int] | None = None
        low, high = 40, 95
        try:
            while low <= high:
                quality = (low + high) // 2
                path, size = save_candidate(img, quality, candidate_paths)
                if size <= BODY_IMAGE_TARGET_BYTES:
                    if best is None or size > best[1]:
                        best = (path, size, quality)
                    low = quality + 1
                else:
                    high = quality - 1
            return best
        finally:
            keep = best[0] if best else None
            for path in candidate_paths:
                if path != keep:
                    path.unlink(missing_ok=True)

    with Image.open(image.path) as img:
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img.convert("RGBA"), mask=img.convert("RGBA").getchannel("A"))
            base = background
        else:
            base = img.convert("RGB")

        scale = 1.0
        working = base
        while min(working.size) >= 320:
            candidate = best_quality_under_limit(working)
            if candidate:
                path, size, quality = candidate
                return LocalImage(
                    path=path,
                    mime="image/jpeg",
                    width=working.width,
                    height=working.height,
                    original_bytes=image.original_bytes,
                    upload_bytes=size,
                    quality=quality,
                    scale=scale,
                )
            scale *= 0.9
            next_size = (max(1, int(base.width * scale)), max(1, int(base.height * scale)))
            working = base.resize(next_size, Image.LANCZOS)
    raise SystemExit(f"Could not compress body image {image.path} under 1MB.")


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
    return width, height


def normalize_body_image_with_sips(image: LocalImage, pillow_exc: Exception) -> LocalImage:
    try:
        width, height = image_size_with_sips(image.path)
    except Exception as exc:  # pragma: no cover - platform fallback
        raise SystemExit(
            f"Body image {image.path} is {image.mime} or larger than 1MB. "
            "Install Pillow or provide jpg/png body images under 1MB."
        ) from pillow_exc or exc

    def save_candidate(quality: int, max_side: int | None, candidate_paths: list[Path]) -> tuple[Path, int]:
        out = tempfile.NamedTemporaryFile(prefix="wechat-body-", suffix=".jpg", delete=False)
        out.close()
        cmd = ["sips"]
        if max_side:
            cmd.extend(["-Z", str(max_side)])
        cmd.extend(["-s", "format", "jpeg", "-s", "formatOptions", str(quality), str(image.path), "--out", out.name])
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        path = Path(out.name)
        candidate_paths.append(path)
        return path, path.stat().st_size

    def best_quality_under_limit(max_side: int | None) -> tuple[Path, int, int] | None:
        candidate_paths: list[Path] = []
        best: tuple[Path, int, int] | None = None
        low, high = 40, 100
        try:
            while low <= high:
                quality = (low + high) // 2
                path, size = save_candidate(quality, max_side, candidate_paths)
                if size <= BODY_IMAGE_TARGET_BYTES:
                    if best is None or size > best[1]:
                        best = (path, size, quality)
                    low = quality + 1
                else:
                    high = quality - 1
            return best
        finally:
            keep = best[0] if best else None
            for path in candidate_paths:
                if path != keep:
                    path.unlink(missing_ok=True)

    scale = 1.0
    max_side = max(width, height)
    current_max_side: int | None = None
    while int(max_side * scale) >= 320:
        candidate = best_quality_under_limit(current_max_side)
        if candidate:
            path, size, quality = candidate
            out_width, out_height = image_size_with_sips(path)
            return LocalImage(
                path=path,
                mime="image/jpeg",
                width=out_width,
                height=out_height,
                original_bytes=image.original_bytes,
                upload_bytes=size,
                quality=quality,
                scale=scale,
            )
        scale *= 0.9
        current_max_side = max(320, int(max_side * scale))
    raise SystemExit(f"Could not compress body image {image.path} under 1MB.")


def upload_body_images(content_html: str, access_token: str) -> tuple[str, list[dict[str, str]]]:
    uploads: list[dict[str, str]] = []

    def replace(match: re.Match[str]) -> str:
        quote = match.group(1)
        data_uri = match.group(2)
        source_image = decode_data_image(data_uri, "png")
        image: LocalImage | None = None
        upload: dict[str, str] | None = None
        try:
            image = normalize_body_image(source_image)
            resp = api_post_multipart("/cgi-bin/media/uploadimg", {}, {"media": image}, access_token)
            url = str(resp["url"])
            upload = {
                "kind": "body",
                "local_path": str(image.path),
                "url": url,
                "original_bytes": str(source_image.original_bytes or source_image.path.stat().st_size),
                "upload_bytes": str(image.upload_bytes or image.path.stat().st_size),
                "compressed": str(image.path != source_image.path).lower(),
                "quality": str(image.quality),
                "scale": f"{image.scale:.4f}",
            }
            uploads.append(upload)
            return f"src={quote}{url}{quote}"
        finally:
            cleanup_temp_image(image)
            if image is None or image.path != source_image.path:
                cleanup_temp_image(source_image)
            if upload is not None:
                upload["local_path_removed"] = str(not Path(upload["local_path"]).exists()).lower()

    return DATA_IMAGE_RE.sub(replace, content_html), uploads


def upload_cover(manifest: dict[str, Any], access_token: str) -> dict[str, str]:
    cover = manifest.get("wechat_cover") or manifest.get("cover") or {}
    src = str(cover.get("src") or "").strip()
    if not src.startswith("data:image/"):
        raise SystemExit("Manifest cover.src must be a data:image URI for API publishing.")
    image = decode_data_image(src, "png")
    result: dict[str, str] | None = None
    try:
        resp = api_post_multipart("/cgi-bin/material/add_material?type=image", {}, {"media": image}, access_token)
        result = {
            "thumb_media_id": str(resp["media_id"]),
            "url": str(resp.get("url", "")),
            "local_path": str(image.path),
            "width": str(image.width),
            "height": str(image.height),
        }
        return result
    finally:
        cleanup_temp_image(image)
        if result is not None:
            result["local_path_removed"] = str(not Path(result["local_path"]).exists()).lower()


def format_crop_value(values: tuple[float, float, float, float]) -> str:
    return "_".join(f"{max(0.0, min(1.0, value)):.6f}".rstrip("0").rstrip(".") for value in values)


def crop_for_ratio(width: int, height: int, target_ratio: float) -> str:
    if width <= 0 or height <= 0:
        width, height = 16, 9
    aspect = width / height
    if aspect > target_ratio:
        crop_width = target_ratio / aspect
        x1 = (1 - crop_width) / 2
        return format_crop_value((x1, 0, 1 - x1, 1))
    crop_height = aspect / target_ratio
    y1 = (1 - crop_height) / 2
    return format_crop_value((0, y1, 1, 1 - y1))


def crop_values_for_cover(width: int, height: int) -> dict[str, str]:
    return {
        "pic_crop_235_1": crop_for_ratio(width, height, 2.35),
        "pic_crop_1_1": crop_for_ratio(width, height, 1.0),
    }


def manifest_cover_crop_values(manifest: dict[str, Any], width: int, height: int) -> dict[str, str]:
    wechat_cover = manifest.get("wechat_cover") if isinstance(manifest.get("wechat_cover"), dict) else {}
    values = wechat_cover.get("crop_values") if isinstance(wechat_cover.get("crop_values"), dict) else {}
    result = crop_values_for_cover(width, height)
    for key in ("pic_crop_235_1", "pic_crop_1_1"):
        value = str(values.get(key, "")).strip()
        if value:
            result[key] = value
    return result


def build_draft_payload(
    manifest: dict[str, Any],
    content_html: str,
    thumb_media_id: str,
    content_source_url: str,
    crop_values: dict[str, str] | None = None,
) -> dict[str, Any]:
    title = str(manifest.get("title", "")).strip()
    if not title:
        raise SystemExit("Manifest title is empty.")
    author = str(manifest.get("author", "")).strip()
    digest = str(manifest.get("digest", "")).strip()[:120]
    comment = manifest.get("comment") if isinstance(manifest.get("comment"), dict) else {}
    need_open_comment = int(comment.get("need_open_comment", 1))
    only_fans_can_comment = int(comment.get("only_fans_can_comment", 0))
    article: dict[str, Any] = {
        "article_type": "news",
        "title": title,
        "author": author,
        "digest": digest,
        "content": content_html,
        "content_source_url": content_source_url,
        "thumb_media_id": thumb_media_id,
        "need_open_comment": 1 if need_open_comment else 0,
        "only_fans_can_comment": 1 if only_fans_can_comment else 0,
        **(crop_values or crop_values_for_cover(0, 0)),
    }
    return {"articles": [article]}


def summarize_draft_payload(draft_payload: dict[str, Any]) -> dict[str, Any]:
    article = draft_payload["articles"][0]
    return {
        "article_count": len(draft_payload["articles"]),
        "title": article["title"],
        "author": article.get("author", ""),
        "digest": article["digest"],
        "thumb_media_id": article["thumb_media_id"],
        "need_open_comment": article.get("need_open_comment"),
        "only_fans_can_comment": article.get("only_fans_can_comment"),
        "pic_crop_235_1": article["pic_crop_235_1"],
        "pic_crop_1_1": article["pic_crop_1_1"],
    }


def validate_manifest(manifest: dict[str, Any], content_html: str) -> dict[str, Any]:
    title = str(manifest.get("title", "")).strip()
    digest = str(manifest.get("digest", "")).strip()
    cover_src = str(((manifest.get("wechat_cover") or manifest.get("cover")) or {}).get("src", "")).strip()
    if not title:
        raise SystemExit("Manifest title is empty.")
    if not digest:
        raise SystemExit("Manifest digest is empty.")
    if not content_html.strip():
        raise SystemExit("Manifest content_html is empty.")
    unstable_tags = sorted({match.group(1).lower() for match in WECHAT_DRAFT_UNSTABLE_TAG_RE.finditer(content_html)})
    if unstable_tags:
        raise SystemExit(
            "Manifest content_html contains tags that can create extra blank editable lines in the WeChat draft box: "
            + ", ".join(unstable_tags)
            + ". Regenerate the manifest with the paragraph-only draft renderer."
        )
    if re.search(r'<p\b[^>]*>\s*</p>', content_html, flags=re.I):
        raise SystemExit("Manifest content_html contains an empty paragraph that would appear as a blank line in the draft box.")
    if "```" in content_html:
        raise SystemExit("Manifest content_html still contains raw fenced-code backticks. Regenerate the manifest.")
    if VISUAL_PLACEHOLDER_RE.search(content_html):
        raise SystemExit("Manifest content_html still contains unresolved {{visual:*}} placeholders.")
    if not cover_src.startswith("data:image/"):
        raise SystemExit("Manifest cover.src must be a data:image URI for API publishing.")
    data_images = DATA_IMAGE_RE.findall(content_html)
    if not data_images:
        raise SystemExit("Manifest content_html has no embedded data:image assets to upload.")
    return {
        "title": title,
        "digest_length": len(digest),
        "content_html_length": len(content_html),
        "body_data_image_count": len(data_images),
        "cover_is_data_uri": True,
        "draft_html_mode": "paragraph_only",
    }


def check_or_open_draft_switch(access_token: str, open_switch: bool) -> dict[str, Any]:
    resp = api_post_json("/cgi-bin/draft/switch?checkonly=1", {}, access_token)
    if resp.get("is_open") == 0 and open_switch:
        resp = api_post_json("/cgi-bin/draft/switch", {}, access_token)
    return resp


def create_draft(payload: dict[str, Any], access_token: str) -> str:
    resp = api_post_json("/cgi-bin/draft/add", payload, access_token)
    return str(resp["media_id"])


def verify_draft(media_id: str, expected_title: str, access_token: str) -> dict[str, Any]:
    resp = api_post_json("/cgi-bin/draft/get", {"media_id": media_id}, access_token)
    articles = (resp.get("news_item") or resp.get("articles") or [])
    first = articles[0] if articles else {}
    returned_title = str(first.get("title", "")).strip() if isinstance(first, dict) else ""
    return {
        "verified": returned_title == expected_title,
        "title": returned_title,
        "article_count": len(articles) if isinstance(articles, list) else 0,
    }


def send_preview(
    media_id: str,
    args: argparse.Namespace,
    manifest: dict[str, Any],
    account: dict[str, str],
    access_token: str,
) -> dict[str, Any]:
    preview = manifest.get("preview") or {}
    payload: dict[str, Any] = {"mpnews": {"media_id": media_id}, "msgtype": "mpnews"}
    if args.preview_openid:
        payload["touser"] = args.preview_openid.strip()
    else:
        preview_account = (args.preview_account or preview.get("account") or account.get("preview_account") or "").strip()
        if not preview_account:
            raise SystemExit("Preview account is empty. Pass --preview-account or set manifest.preview.account.")
        payload["towxname"] = preview_account
    return api_post_json("/cgi-bin/message/mass/preview", payload, access_token)


def main() -> None:
    args = parse_args()
    manifest = read_json(args.manifest.resolve())
    config = read_config(args.config)
    env_file = find_env_file(args.manifest, args.env_file)
    env = account_config.read_env_file(env_file)
    account = account_config.find_account_profile(env, args.account, include_credentials=True)
    token_cache = args.token_cache.expanduser()
    if token_cache == DEFAULT_TOKEN_CACHE:
        token_cache = account_config.account_token_cache_path(DEFAULT_TOKEN_CACHE, account)
    args.token_cache = token_cache

    content_html = str(manifest.get("content_html", ""))
    validation = validate_manifest(manifest, content_html)

    result: dict[str, Any] = {
        "manifest": str(args.manifest.resolve()),
        "dry_run": args.dry_run,
        "env_file": str(env_file.resolve()) if env_file and env_file.exists() else "",
        "account": {
            "selector": account.get("selector", ""),
            "alias": account.get("alias", ""),
            "name": account.get("name", ""),
        },
        "token_cache": str(args.token_cache),
        "validation": validation,
    }
    draft_payload: dict[str, Any]

    if args.dry_run:
        cover_src = str(((manifest.get("wechat_cover") or manifest.get("cover")) or {}).get("src", ""))
        cover_image = decode_data_image(cover_src, "png")
        try:
            crop_values = manifest_cover_crop_values(manifest, cover_image.width, cover_image.height)
        finally:
            cleanup_temp_image(cover_image)
        draft_payload = build_draft_payload(
            manifest,
            content_html,
            "DRY_RUN_THUMB_MEDIA_ID",
            args.content_source_url,
            crop_values,
        )
        result["draft_payload_summary"] = summarize_draft_payload(draft_payload)
        if args.include_payload:
            result["draft_payload"] = draft_payload
    else:
        access_token = get_access_token(args, config, account)
        if args.check_draft_switch:
            result["draft_switch"] = check_or_open_draft_switch(access_token, args.open_draft_switch)
        uploaded_content_html, body_uploads = upload_body_images(content_html, access_token)
        cover_upload = upload_cover(manifest, access_token)
        crop_values = manifest_cover_crop_values(manifest, int(cover_upload["width"]), int(cover_upload["height"]))
        draft_payload = build_draft_payload(
            manifest,
            uploaded_content_html,
            cover_upload["thumb_media_id"],
            args.content_source_url,
            crop_values,
        )
        media_id = create_draft(draft_payload, access_token)
        result.update(
            {
                "body_upload_count": len(body_uploads),
                "body_uploads": body_uploads,
                "cover_upload": {
                    "thumb_media_id": cover_upload["thumb_media_id"],
                    "url": cover_upload.get("url", ""),
                    "width": cover_upload.get("width", ""),
                    "height": cover_upload.get("height", ""),
                },
                "draft_payload_summary": summarize_draft_payload(draft_payload),
                "draft_media_id": media_id,
            }
        )
        if args.include_payload:
            result["draft_payload"] = draft_payload
        if args.verify_draft:
            result["draft_verification"] = verify_draft(media_id, validation["title"], access_token)
        if args.send_preview:
            result["preview"] = send_preview(media_id, args, manifest, account, access_token)

    out = (args.out or args.manifest.with_suffix(".wechat-api-result.json")).resolve()
    write_json(out, result)
    print(f"Wrote {out}")
    if result.get("draft_media_id"):
        print(f"Created draft media_id: {result['draft_media_id']}")
    if result.get("preview"):
        print("Preview sent.")


if __name__ == "__main__":
    main()
