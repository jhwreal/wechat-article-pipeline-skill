#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import binascii
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
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

import build_wechat_article_workbench as workbench_builder
from atomic_files import atomic_write_json, atomic_write_text, manifest_fingerprint
import publish_run_state as run_state
import wechat_account_config as account_config


DEFAULT_API_CONFIG = Path.home() / ".codex" / "wechat-article-pipeline" / "wechat-api-config.json"
DEFAULT_TOKEN_CACHE = Path.home() / ".codex" / "wechat-article-pipeline" / "wechat-token-cache.json"
API_BASE = "https://api.weixin.qq.com"
DATA_IMAGE_RE = re.compile(r'\bsrc\s*=\s*(["\'])(data:image/[^"\']+)\1', re.I)
IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.I | re.S)
IMG_SRC_RE = re.compile(r'<img\b[^>]*?\bsrc\s*=\s*(["\'])(.*?)\1', re.I | re.S)
VISUAL_PLACEHOLDER_RE = re.compile(r"\{\{visual:[^}]+\}\}")
WECHAT_DRAFT_UNSTABLE_TAG_RE = re.compile(r"</?(section|div|blockquote|pre|ul|ol)\b", re.I)
MAX_BODY_IMAGE_BYTES = 1024 * 1024
# WeChat uploadimg requires body images under 1 MB; target 900 KiB for a
# practical margin while keeping generated article images readable.
BODY_IMAGE_TARGET_BYTES = 900 * 1024
DATA_IMAGE_HEADER_RE = re.compile(r"^data:(image/[a-z0-9.+-]+);base64$", re.I)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
URL_CONTROL_RE = re.compile(r"[\x00-\x20\x7f]+")
URL_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*$", re.I)
DATA_IMAGE_PREFIX = "data:image/"
ALLOWED_DRAFT_TAGS = {
    "p", "img", "a", "code", "strong", "span", "em", "br",
    "table", "thead", "tbody", "tr", "th", "td",
}
VOID_DRAFT_TAGS = {"img", "br"}
ALLOWED_DRAFT_ATTRIBUTES = {
    "p": {"style"},
    "img": {"alt", "src", "style"},
    "a": {"href", "style"},
    "code": {"style"},
    "strong": {"style"},
    "span": {"style"},
    "em": set(),
    "br": set(),
    "table": {"style"},
    "thead": set(),
    "tbody": set(),
    "tr": set(),
    "th": {"style"},
    "td": {"style"},
}
ERROR_HELP = {
    40164: "公众号接口 IP 白名单校验失败。发布流程已立即停止，未创建草稿。",
    48001: "公众号没有开通或没有获得该接口权限。",
    89503: "此次调用需要管理员确认。请到微信侧完成确认后重试。",
    89506: "管理员拒绝了本 IP 的调用请求。按官方提示等待后再试。",
    89507: "管理员拒绝了本 IP 的调用请求。按官方提示等待后再试。",
}
IPV4_IN_ERROR_RE = re.compile(r"(?<![0-9.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9.])")


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
    parser.add_argument(
        "--create-draft",
        action="store_true",
        help="Create the WeChat draft through network APIs. Omit this flag for the default local dry-run.",
    )
    parser.add_argument("--resume", action="store_true", help="Resume safe pending work from an existing --out receipt.")
    parser.add_argument(
        "--retry-preview",
        action="store_true",
        help="With --resume, explicitly retry a preview whose prior outcome is unknown.",
    )
    parser.add_argument(
        "--increment-original-issue",
        action="store_true",
        help=(
            "After a successful draft creation, advance the manifest article_signature issue value in .env. "
            "Signed manifests enable this automatically; the flag remains for compatibility."
        ),
    )
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
    atomic_write_json(path, data)


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
    atomic_write_json(path, config, mode=0o600)


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
        numeric_errcode = int(errcode)
        errmsg = str(result.get("errmsg", ""))
        help_text = ERROR_HELP.get(numeric_errcode, "请用官方 API 诊断工具结合 errmsg/rid 排查。")
        if numeric_errcode == 40164:
            ip_match = IPV4_IN_ERROR_RE.search(errmsg)
            outbound_ip = ip_match.group(0) if ip_match else "未能从接口错误中识别"
            raise SystemExit(
                "WECHAT_IP_WHITELIST_BLOCKED\n"
                f"{help_text}\n"
                f"当前出口 IP：{outbound_ip}\n"
                "请立即告知用户，并等待用户把该 IP 加入微信公众平台开发配置的 IP 白名单；"
                "在用户确认前不要继续公众号上传或任何后续跨平台发布。"
            )
        raise SystemExit(f"WeChat API error {errcode}: {errmsg}\n{help_text}")
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


def decode_data_image_payload(data_uri: str) -> tuple[str, bytes]:
    if "," not in data_uri:
        raise SystemExit("Invalid data image URI: missing payload separator.")
    header, encoded = data_uri.split(",", 1)
    match = DATA_IMAGE_HEADER_RE.fullmatch(header.strip())
    if not match:
        raise SystemExit("Invalid data image URI: expected data:image/<type>;base64,...")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SystemExit("Invalid data image URI: malformed base64 payload.") from exc
    if not raw:
        raise SystemExit("Invalid data image URI: image payload is empty.")
    declared_mime = match.group(1).lower()
    canonical_declared = {
        "image/jpg": "image/jpeg",
        "image/x-ms-bmp": "image/bmp",
    }.get(declared_mime, declared_mime)
    detected_mime = ""
    if (
        len(raw) >= 24
        and raw.startswith(b"\x89PNG\r\n\x1a\n")
        and raw[12:16] == b"IHDR"
        and int.from_bytes(raw[16:20], "big") > 0
        and int.from_bytes(raw[20:24], "big") > 0
    ):
        detected_mime = "image/png"
    elif raw.startswith(b"\xff\xd8\xff"):
        detected_mime = "image/jpeg"
    elif (
        len(raw) >= 10
        and raw[:6] in {b"GIF87a", b"GIF89a"}
        and int.from_bytes(raw[6:8], "little") > 0
        and int.from_bytes(raw[8:10], "little") > 0
    ):
        detected_mime = "image/gif"
    elif len(raw) >= 16 and raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        detected_mime = "image/webp"
    elif len(raw) >= 26 and raw.startswith(b"BM"):
        detected_mime = "image/bmp"
    if not detected_mime:
        raise SystemExit("Invalid data image URI: payload is not a recognized image format.")
    if canonical_declared != detected_mime:
        raise SystemExit(
            "Invalid data image URI: declared MIME type does not match the image payload "
            f"({declared_mime} != {detected_mime})."
        )
    return detected_mime, raw


def decode_data_image(data_uri: str, suffix_hint: str) -> LocalImage:
    mime, raw = decode_data_image_payload(data_uri)
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
    if width <= 0 or height <= 0:
        Path(tmp.name).unlink(missing_ok=True)
        raise SystemExit(
            "Image payload could not be decoded or has invalid dimensions. "
            "Install Pillow or provide a valid supported image."
        )
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


def is_data_image_uri(value: str) -> bool:
    return value[: len(DATA_IMAGE_PREFIX)].lower() == DATA_IMAGE_PREFIX


def _safe_draft_url(value: str, *, image: bool) -> bool:
    stripped = value.strip()
    colon = stripped.find(":")
    if colon < 0:
        return True
    scheme = URL_CONTROL_RE.sub("", stripped[:colon]).lower()
    if not URL_SCHEME_RE.fullmatch(scheme):
        return True
    if scheme in {"http", "https"}:
        return True
    if not image and scheme == "mailto":
        return True
    if not image or scheme != "data":
        return False
    comma = stripped.find(",", colon + 1)
    if comma < 0 or comma - colon > 256:
        return False
    header = URL_CONTROL_RE.sub("", stripped[:comma]).lower()
    return header.startswith(DATA_IMAGE_PREFIX)


class DraftHTMLSafetyParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []

    def _validate_start(
        self, tag: str, attrs: list[tuple[str, str | None]], *, self_closing: bool
    ) -> None:
        tag = tag.lower()
        if tag not in ALLOWED_DRAFT_TAGS:
            raise ValueError(f"unsupported HTML tag: <{tag}>")
        allowed = ALLOWED_DRAFT_ATTRIBUTES[tag]
        seen: set[str] = set()
        values: dict[str, str] = {}
        for raw_name, raw_value in attrs:
            name = raw_name.lower()
            if name in seen:
                raise ValueError(f"duplicate {name} attribute on <{tag}>")
            seen.add(name)
            if name not in allowed:
                raise ValueError(f"unsupported {name} attribute on <{tag}>")
            value = raw_value or ""
            values[name] = value
            if name == "style" and re.search(
                r"(?:expression\s*\(|url\s*\(|@import|behavior\s*:)", value, re.I
            ):
                raise ValueError(f"unsafe inline style on <{tag}>")
        if tag == "a":
            href = values.get("href", "")
            if not href or not _safe_draft_url(href, image=False):
                raise ValueError("unsafe or missing link href")
        if tag == "img":
            source = values.get("src", "")
            if not source or not _safe_draft_url(source, image=True):
                raise ValueError("unsafe or missing image src")
        if tag in VOID_DRAFT_TAGS:
            return
        if self_closing:
            return
        self.stack.append(tag)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._validate_start(tag, attrs, self_closing=False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._validate_start(tag, attrs, self_closing=True)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in VOID_DRAFT_TAGS or not self.stack or self.stack[-1] != tag:
            raise ValueError(f"unbalanced closing tag: </{tag}>")
        self.stack.pop()

    def handle_comment(self, _data: str) -> None:
        raise ValueError("HTML comments are not allowed")

    def handle_decl(self, _decl: str) -> None:
        raise ValueError("HTML declarations are not allowed")

    def handle_pi(self, _data: str) -> None:
        raise ValueError("HTML processing instructions are not allowed")

    def close(self) -> None:
        super().close()
        if self.stack:
            raise ValueError(f"unclosed HTML tag: <{self.stack[-1]}>")


def validate_draft_html_safety(content_html: str) -> None:
    parser = DraftHTMLSafetyParser()
    try:
        parser.feed(content_html)
        parser.close()
    except ValueError as exc:
        raise SystemExit(f"Manifest content_html is unsafe or malformed: {exc}.") from exc


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
    if not is_data_image_uri(src):
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
    if not isinstance(manifest, dict):
        raise SystemExit("Publish manifest must be a JSON object.")
    source_state = manifest.get("source_state")
    if source_state is not None:
        if not isinstance(source_state, dict):
            raise SystemExit("Manifest source_state must be an object.")
        for key in ("core_revision", "manifest_revision"):
            value = source_state.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise SystemExit(f"Manifest source_state.{key} must be a non-negative integer.")
        if source_state.get("core_revision") != source_state.get("manifest_revision"):
            raise SystemExit("Manifest source revision mismatch.")
        asset_state = str(source_state.get("asset_state", "")).strip()
        if asset_state != "ready" or source_state.get("stale_visuals") or source_state.get("missing_visuals"):
            raise SystemExit("Manifest assets are not ready (stale, missing, or failed).")
    title = str(manifest.get("title", "")).strip()
    digest = str(manifest.get("digest", "")).strip()
    source_fingerprint = str(manifest.get("source_fingerprint", "")).strip()
    if source_fingerprint and not SHA256_RE.fullmatch(source_fingerprint):
        raise SystemExit("Manifest source_fingerprint must be a lowercase SHA-256 digest.")
    cover = manifest.get("wechat_cover") or manifest.get("cover") or {}
    if not isinstance(cover, dict):
        raise SystemExit("Manifest cover must be an object.")
    cover_src = str(cover.get("src", "")).strip()
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
    if not is_data_image_uri(cover_src):
        raise SystemExit("Manifest cover.src must be a data:image URI for API publishing.")
    body_image_sources: list[str] = []
    for image_tag in IMG_TAG_RE.finditer(content_html):
        source_match = IMG_SRC_RE.search(content_html, image_tag.start(), image_tag.end())
        if not source_match:
            raise SystemExit(
                "Every manifest body <img> must have a quoted src attribute so it can be uploaded safely."
            )
        body_image_sources.append(source_match.group(2).strip())
    unsupported_sources = [
        source for source in body_image_sources if not is_data_image_uri(source)
    ]
    if unsupported_sources:
        sample = unsupported_sources[0]
        if len(sample) > 120:
            sample = sample[:117] + "..."
        raise SystemExit(
            "Manifest body images must be embedded data:image URIs for API publishing; "
            f"unsupported src: {sample!r}. Regenerate the publish manifest from local assets."
        )
    decode_data_image_payload(cover_src)
    for source in body_image_sources:
        if source != cover_src:
            decode_data_image_payload(source)
    # Base64 has already been validated strictly above. Replacing only its
    # quoted src value keeps every tag, attribute, link, and style visible to
    # the structural safety parser without making it walk megabytes of inert
    # image payload character by character.
    safety_html = DATA_IMAGE_RE.sub(
        lambda match: f"src={match.group(1)}data:image/png;base64,AA=={match.group(1)}",
        content_html,
    )
    validate_draft_html_safety(safety_html)
    table_count = len(re.findall(r"<table\b", content_html, re.I))
    return {
        "title": title,
        "digest_length": len(digest),
        "content_html_length": len(content_html),
        "body_data_image_count": len(body_image_sources),
        "table_count": table_count,
        "cover_is_data_uri": True,
        "draft_html_mode": "paragraph_and_table_safe",
    }


def validate_execution_mode(args: argparse.Namespace) -> bool:
    if args.dry_run and args.create_draft:
        raise SystemExit("--dry-run and --create-draft cannot be used together.")
    if args.retry_preview and not args.resume:
        raise SystemExit("--retry-preview requires --resume.")
    if args.resume and not args.out:
        raise SystemExit("--resume requires an explicit --out result path.")
    if args.open_draft_switch:
        args.check_draft_switch = True
    network_flags = []
    for flag in (
        "check_draft_switch",
        "open_draft_switch",
        "verify_draft",
        "send_preview",
        "increment_original_issue",
        "force_refresh_token",
        "resume",
        "retry_preview",
    ):
        if getattr(args, flag):
            network_flags.append("--" + flag.replace("_", "-"))
    if network_flags and not args.create_draft:
        raise SystemExit(
            "Network API flags require --create-draft: "
            + ", ".join(network_flags)
            + ". Omit them for local dry-run validation."
        )
    return not args.create_draft


def manifest_original_issue(manifest: dict[str, Any], *, required: bool = False) -> tuple[str, str, int] | None:
    signature_value = manifest.get("article_signature")
    signature = signature_value if isinstance(signature_value, dict) else {}
    key = str(signature.get("issue_env_key", "")).strip()
    raw_issue = str(signature.get("issue", "")).strip()
    if not key and not raw_issue:
        if required:
            raise SystemExit(
                "Manifest article_signature lacks issue_env_key/issue; regenerate the manifest before incrementing."
            )
        return None
    if not key or not raw_issue:
        raise SystemExit(
            "Manifest article_signature must contain both issue_env_key and issue; regenerate the manifest."
        )
    try:
        issue = int(raw_issue)
    except ValueError as exc:
        raise SystemExit(f"Manifest article_signature.issue is not an integer: {raw_issue!r}") from exc
    return key, raw_issue, issue


def manifest_original_issue_policy(manifest: dict[str, Any]) -> str:
    signature_value = manifest.get("article_signature")
    signature = signature_value if isinstance(signature_value, dict) else {}
    policy = str(signature.get("counter_policy", "consume_on_success")).strip()
    if policy not in {"consume_on_success", "reuse_previous"}:
        raise SystemExit(
            "Manifest article_signature.counter_policy must be "
            "'consume_on_success' or 'reuse_previous'."
        )
    return policy


def apply_original_issue_policy(args: argparse.Namespace, manifest: dict[str, Any]) -> None:
    """Apply the signed manifest's first-draft or same-session revision policy."""
    if not args.create_draft or args.resume or manifest_original_issue(manifest) is None:
        return
    policy = manifest_original_issue_policy(manifest)
    if policy == "reuse_previous":
        if args.increment_original_issue:
            raise SystemExit(
                "A same-session revision manifest reuses the previous original issue and cannot "
                "be combined with --increment-original-issue."
            )
        args.increment_original_issue = False
        return
    args.increment_original_issue = True


def validate_original_issue_preflight(manifest: dict[str, Any], env_file: Path | None) -> None:
    key, raw_issue, issue = manifest_original_issue(manifest, required=True)
    policy = manifest_original_issue_policy(manifest)
    if env_file is None or not env_file.expanduser().is_file():
        raise SystemExit("Cannot validate original issue: the resolved env file is missing.")

    current = account_config.read_env_file(env_file).get(key)
    expected = raw_issue if policy == "consume_on_success" else str(issue + 1)
    if current == expected:
        return
    if policy == "consume_on_success" and current == str(issue + 1):
        raise SystemExit(
            f"Manifest original issue {raw_issue} has already been consumed ({key}={current}). "
            "Regenerate the publish manifest before creating another draft."
        )
    if current is None:
        raise SystemExit(f"Cannot validate original issue: {key} is missing from {env_file.expanduser()}.")
    if policy == "reuse_previous":
        raise SystemExit(
            f"Same-session revision issue {raw_issue} requires {key}={issue + 1}, but found {current}. "
            "Rebuild without --same-session-revision for a new article, or restore the expected counter."
        )
    raise SystemExit(
        f"Manifest original issue {raw_issue} does not match {key}={current}. "
        "Regenerate the publish manifest before creating a draft."
    )


def increment_original_issue(manifest: dict[str, Any], env_file: Path | None) -> dict[str, str]:
    if not env_file:
        raise SystemExit("Cannot increment original issue without an env file.")
    key, raw_issue, issue = manifest_original_issue(manifest, required=True)
    next_issue = issue + 1
    account_config.compare_and_set_env_value(env_file, key, raw_issue, str(next_issue))
    return {"env_file": str(env_file.expanduser()), "issue_env_key": key, "next_issue": str(next_issue)}


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
    if not isinstance(articles, list) or not articles:
        raise RuntimeError("Draft verification failed: WeChat returned no article items.")
    first = articles[0] if articles else {}
    returned_title = str(first.get("title", "")).strip() if isinstance(first, dict) else ""
    expected_title = expected_title.strip()
    if returned_title != expected_title:
        raise RuntimeError(
            "Draft verification failed: returned title does not match the manifest "
            f"({returned_title!r} != {expected_title!r})."
        )
    returned_content = str(first.get("content", "")) if isinstance(first, dict) else ""
    table_count = len(re.findall(r"<table\b", returned_content, re.I))
    return {
        "verified": True,
        "title": returned_title,
        "article_count": len(articles) if isinstance(articles, list) else 0,
        "table_count": table_count,
        "raw_markdown_table_header_count": returned_content.count("| 模型 |"),
    }


def verify_draft_preserves_tables(
    media_id: str,
    expected_title: str,
    access_token: str,
    expected_table_count: int,
) -> dict[str, Any]:
    result = verify_draft(media_id, expected_title, access_token)
    actual_table_count = int(result.get("table_count", 0))
    if actual_table_count != expected_table_count:
        raise RuntimeError(
            "Draft verification failed: WeChat did not preserve the expected number of tables "
            f"({actual_table_count} != {expected_table_count})."
        )
    return result


def send_preview(
    media_id: str,
    args: argparse.Namespace,
    manifest: dict[str, Any],
    account: dict[str, str],
    access_token: str,
) -> dict[str, Any]:
    target = normalize_preview_target(args, manifest, account)
    payload: dict[str, Any] = {"mpnews": {"media_id": media_id}, "msgtype": "mpnews"}
    if not target["value"]:
        raise SystemExit("Preview account is empty. Pass --preview-account or set manifest.preview.account.")
    if target["kind"] == "openid":
        payload["touser"] = target["value"]
    else:
        payload["towxname"] = target["value"]
    return api_post_json("/cgi-bin/message/mass/preview", payload, access_token)


def normalize_preview_target(
    args: argparse.Namespace,
    manifest: dict[str, Any],
    account: dict[str, str],
) -> dict[str, str]:
    preview_openid = str(args.preview_openid or "").strip()
    if preview_openid:
        return {"kind": "openid", "value": preview_openid}
    preview = manifest.get("preview") if isinstance(manifest.get("preview"), dict) else {}
    preview_account = str(
        args.preview_account or preview.get("account") or account.get("preview_account") or ""
    ).strip()
    return {"kind": "account", "value": preview_account}


def resolved_env_file(env_file: Path | None) -> str:
    return str(env_file.expanduser().resolve()) if env_file else ""


def requested_publish_operations(args: argparse.Namespace) -> list[str]:
    operations = ["draft_add"]
    if args.increment_original_issue:
        operations.append("increment_original_issue")
    if args.verify_draft:
        operations.append("verify_draft")
    if args.send_preview:
        operations.append("send_preview")
    return operations


def operation_requested(run: dict[str, Any], operation: str) -> bool:
    operation_state = run.get("operation_state")
    if not isinstance(operation_state, dict):
        return False
    entry = operation_state.get(operation)
    return isinstance(entry, dict) and bool(entry.get("requested", True))


def operation_state_value(run: dict[str, Any], operation: str) -> str:
    operation_state = run.get("operation_state")
    if not isinstance(operation_state, dict):
        return ""
    entry = operation_state.get(operation)
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("state", ""))


def bind_side_effect_parameters(
    run: dict[str, Any],
    args: argparse.Namespace,
    manifest: dict[str, Any],
    account: dict[str, str],
    env_file: Path | None,
) -> None:
    operation_state = run["operation_state"]
    if operation_requested(run, "send_preview"):
        operation_state["send_preview"]["parameters"] = {
            "target": normalize_preview_target(args, manifest, account)
        }
    if operation_requested(run, "increment_original_issue"):
        operation_state["increment_original_issue"]["parameters"] = {
            "env_file": resolved_env_file(env_file)
        }


def validate_new_run_side_effect_parameters(
    args: argparse.Namespace,
    manifest: dict[str, Any],
    account: dict[str, str],
    env_file: Path | None,
) -> None:
    if args.send_preview and not normalize_preview_target(args, manifest, account)["value"]:
        raise SystemExit("Preview account is empty. Pass --preview-account or set manifest.preview.account.")
    if manifest_original_issue(manifest) is not None:
        validate_original_issue_preflight(manifest, env_file)


def validate_resume_side_effect_parameters(
    run: dict[str, Any],
    args: argparse.Namespace,
    env_file: Path | None,
) -> tuple[argparse.Namespace, Path | None]:
    preview_args = argparse.Namespace(**vars(args))
    stored_env_file = env_file
    operation_state = run.get("operation_state")
    if not isinstance(operation_state, dict):
        raise SystemExit("Cannot resume: existing result receipt has no operation state.")

    if operation_requested(run, "send_preview"):
        preview_entry = operation_state["send_preview"]
        parameters = preview_entry.get("parameters")
        target = parameters.get("target") if isinstance(parameters, dict) else None
        if not isinstance(target, dict) or target.get("kind") not in {"openid", "account"}:
            raise SystemExit("Cannot resume: receipt has no stored preview target parameters.")
        stored_target = {"kind": str(target["kind"]), "value": str(target.get("value", "")).strip()}
        explicit_target: dict[str, str] | None = None
        if str(args.preview_openid or "").strip():
            explicit_target = {"kind": "openid", "value": str(args.preview_openid).strip()}
        elif str(args.preview_account or "").strip():
            explicit_target = {"kind": "account", "value": str(args.preview_account).strip()}
        if explicit_target is not None and explicit_target != stored_target:
            raise SystemExit(
                f"Cannot resume: preview target changed from {stored_target!r} to {explicit_target!r}."
            )
        if stored_target["kind"] == "openid":
            preview_args.preview_openid = stored_target["value"]
            preview_args.preview_account = None
        else:
            preview_args.preview_openid = None
            preview_args.preview_account = stored_target["value"]

    if operation_requested(run, "increment_original_issue"):
        increment_entry = operation_state["increment_original_issue"]
        parameters = increment_entry.get("parameters")
        stored_path = parameters.get("env_file") if isinstance(parameters, dict) else None
        if not isinstance(stored_path, str):
            raise SystemExit("Cannot resume: receipt has no stored env_file parameter.")
        current_path = resolved_env_file(env_file)
        if stored_path != current_path:
            raise SystemExit(f"Cannot resume: env_file changed from {stored_path!r} to {current_path!r}.")
        stored_env_file = Path(stored_path) if stored_path else None

    return preview_args, stored_env_file


def is_publish_journal(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        existing = read_json(path)
    except (OSError, json.JSONDecodeError):
        return False
    operation_state = existing.get("operation_state")
    return isinstance(operation_state, dict) and isinstance(operation_state.get("draft_add"), dict)


def run_checkpointed_operation(
    out: Path,
    run: dict[str, Any],
    operation: str,
    legacy_field: str,
    action: Callable[[], Any],
    *,
    unknown_on_error: bool = False,
) -> None:
    run_state.mark_started(run, operation)
    run["status"] = "partial_success"
    run["last_error"] = None
    run_state.checkpoint(out, run)
    try:
        value = action()
    except BaseException as exc:
        if unknown_on_error:
            run_state.mark_unknown(run, operation, exc)
        else:
            run_state.mark_failed(run, operation, exc)
        run["status"] = "partial_success"
        run_state.checkpoint(out, run)
        raise
    run[legacy_field] = value
    run_state.mark_succeeded(run, operation)
    run["status"] = "partial_success"
    run["last_error"] = None
    run_state.checkpoint(out, run)


def finish_publish_run(out: Path, run: dict[str, Any]) -> None:
    operation_state = run.get("operation_state")
    entries = operation_state.values() if isinstance(operation_state, dict) else []
    if all(not entry.get("requested", True) or entry.get("state") == "succeeded" for entry in entries):
        run["status"] = "success"
        run["last_error"] = None
    run_state.checkpoint(out, run)


def sync_platform_images_to_workbench(
    manifest: dict[str, Any],
    result: dict[str, Any],
    receipt_path: Path,
) -> dict[str, Any]:
    """Expose uploaded body images to the workbench's one-paste adapters."""
    workbench_value = str(manifest.get("workbench_html") or "").strip()
    if not workbench_value:
        return {"status": "skipped", "reason": "manifest has no workbench_html"}
    urls = workbench_builder.platform_image_urls_from_wechat_result(result)
    if not urls:
        return {"status": "skipped", "reason": "successful body image uploads are unavailable"}

    workbench_path = Path(workbench_value).expanduser().resolve()
    if not workbench_path.exists():
        return {
            "status": "skipped",
            "reason": "workbench_html does not exist",
            "workbench_html": str(workbench_path),
        }
    try:
        current = workbench_path.read_text(encoding="utf-8")
        updated = workbench_builder.replace_bootstrap(
            current,
            {
                "platformImageUrls": urls,
                "platformImageSource": str(receipt_path.resolve()),
            },
        )
        if updated == current and 'id="wechat-bootstrap"' not in current:
            return {
                "status": "skipped",
                "reason": "workbench template does not support platform image URLs",
                "workbench_html": str(workbench_path),
            }
        if updated != current:
            atomic_write_text(workbench_path, updated)
        return {
            "status": "updated",
            "workbench_html": str(workbench_path),
            "image_count": len(urls),
        }
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "failed",
            "reason": f"{type(exc).__name__}: {exc}"[:240],
            "workbench_html": str(workbench_path),
        }


def validate_resume_receipt(
    out: Path,
    run: dict[str, Any],
    manifest_path: Path,
    account: dict[str, str],
) -> str:
    expected_fingerprint = manifest_fingerprint(manifest_path)
    stored_fingerprint = str(run.get("manifest_sha256", ""))
    if not stored_fingerprint or stored_fingerprint != expected_fingerprint:
        raise SystemExit("Cannot resume: manifest SHA-256 does not match the existing result receipt.")

    stored_account = run.get("account")
    if not isinstance(stored_account, dict):
        raise SystemExit("Cannot resume: existing result receipt has no account identity.")
    for field in ("alias", "name"):
        stored_value = str(stored_account.get(field, ""))
        current_value = str(account.get(field, ""))
        if stored_value != current_value:
            raise SystemExit(
                f"Cannot resume: account {field} changed from {stored_value!r} to {current_value!r}."
            )

    operation_state = run.get("operation_state")
    draft_entry = operation_state.get("draft_add") if isinstance(operation_state, dict) else None
    if not isinstance(draft_entry, dict):
        raise SystemExit("Cannot resume: existing result receipt has no draft_add operation state.")
    media_id = str(run.get("draft_media_id", "")).strip()
    if not media_id:
        error = RuntimeError("draft_add has no draft_media_id; its remote outcome is unknown")
        run_state.mark_unknown(run, "draft_add", error)
        run["status"] = "unknown"
        run_state.checkpoint(out, run)
        raise SystemExit("Cannot resume draft_add without a stored media_id; remote draft creation is unknown.")
    if operation_state_value(run, "draft_add") != "succeeded":
        run_state.mark_succeeded(run, "draft_add")
        run["status"] = "partial_success"
        run_state.checkpoint(out, run)
    return media_id


def resume_publish_run(
    args: argparse.Namespace,
    out: Path,
    manifest: dict[str, Any],
    config: dict[str, Any],
    env_file: Path | None,
    account: dict[str, str],
    validation: dict[str, Any],
) -> dict[str, Any]:
    if not out.exists():
        raise SystemExit(f"--resume requires an existing --out result: {out}")
    run = read_json(out)
    media_id = validate_resume_receipt(out, run, args.manifest, account)
    preview_args, stored_env_file = validate_resume_side_effect_parameters(run, args, env_file)

    preview_state = operation_state_value(run, "send_preview")
    if operation_requested(run, "send_preview") and preview_state in {"in_progress", "unknown"}:
        if preview_state == "in_progress":
            error = RuntimeError("preview may have been sent before its success checkpoint")
            run_state.mark_unknown(run, "send_preview", error)
            run["status"] = "partial_success"
            run_state.checkpoint(out, run)
        if not args.retry_preview:
            raise SystemExit(
                "Cannot safely resume a preview with unknown outcome. Pass --retry-preview to accept duplicate-preview risk."
            )

    needs_access_token = any(
        operation_requested(run, operation) and operation_state_value(run, operation) != "succeeded"
        for operation in ("verify_draft", "send_preview")
    )
    access_token = get_access_token(args, config, account) if needs_access_token else ""

    if operation_requested(run, "verify_draft") and operation_state_value(run, "verify_draft") != "succeeded":
        run_checkpointed_operation(
            out,
            run,
            "verify_draft",
            "draft_verification",
            lambda: verify_draft_preserves_tables(
                media_id,
                validation["title"],
                access_token,
                validation["table_count"],
            ),
        )
    if operation_requested(run, "send_preview") and operation_state_value(run, "send_preview") != "succeeded":
        run_checkpointed_operation(
            out,
            run,
            "send_preview",
            "preview",
            lambda: send_preview(media_id, preview_args, manifest, account, access_token),
            unknown_on_error=True,
        )
    if (
        operation_requested(run, "increment_original_issue")
        and operation_state_value(run, "increment_original_issue") != "succeeded"
    ):
        run_checkpointed_operation(
            out,
            run,
            "increment_original_issue",
            "original_issue_increment",
            lambda: increment_original_issue(manifest, stored_env_file),
        )

    finish_publish_run(out, run)
    return run


def create_publish_run(
    args: argparse.Namespace,
    out: Path,
    manifest: dict[str, Any],
    base_result: dict[str, Any],
    config: dict[str, Any],
    env_file: Path | None,
    account: dict[str, str],
    content_html: str,
    validation: dict[str, Any],
) -> dict[str, Any]:
    validate_new_run_side_effect_parameters(args, manifest, account, env_file)
    run = run_state.new_publish_run(
        base_result,
        manifest_sha256=manifest_fingerprint(args.manifest),
        requested_operations=requested_publish_operations(args),
    )
    bind_side_effect_parameters(run, args, manifest, account, env_file)
    access_token = get_access_token(args, config, account)
    if args.check_draft_switch:
        run["draft_switch"] = check_or_open_draft_switch(access_token, args.open_draft_switch)
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
    run.update(
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
        }
    )
    if args.include_payload:
        run["draft_payload"] = draft_payload

    run_state.mark_started(run, "draft_add")
    run["status"] = "unknown"
    run_state.checkpoint(out, run)
    try:
        media_id = create_draft(draft_payload, access_token)
    except BaseException as exc:
        run_state.mark_unknown(run, "draft_add", exc)
        run["status"] = "unknown"
        run_state.checkpoint(out, run)
        raise

    run["draft_media_id"] = media_id
    run_state.mark_succeeded(run, "draft_add")
    run["status"] = "partial_success"
    run["last_error"] = None
    run_state.checkpoint(out, run)

    if args.verify_draft:
        run_checkpointed_operation(
            out,
            run,
            "verify_draft",
            "draft_verification",
            lambda: verify_draft_preserves_tables(
                media_id,
                validation["title"],
                access_token,
                validation["table_count"],
            ),
        )
    if args.send_preview:
        run_checkpointed_operation(
            out,
            run,
            "send_preview",
            "preview",
            lambda: send_preview(media_id, args, manifest, account, access_token),
            unknown_on_error=True,
        )
    if args.increment_original_issue:
        run_checkpointed_operation(
            out,
            run,
            "increment_original_issue",
            "original_issue_increment",
            lambda: increment_original_issue(manifest, env_file),
        )

    finish_publish_run(out, run)
    return run


def main() -> None:
    args = parse_args()
    dry_run = validate_execution_mode(args)
    args.manifest = args.manifest.expanduser().resolve()
    out = (args.out or args.manifest.with_suffix(".wechat-api-result.json")).expanduser().resolve()
    if not args.resume and is_publish_journal(out):
        raise SystemExit(
            f"Refusing to overwrite existing publish receipt: {out}. Use --resume or choose a different --out path."
        )
    manifest = read_json(args.manifest)
    apply_original_issue_policy(args, manifest)
    config = read_config(args.config)
    env_file = find_env_file(args.manifest, args.env_file)
    env = account_config.read_env_file(env_file)
    account = account_config.find_account_profile(env, args.account, include_credentials=not dry_run)
    token_cache = args.token_cache.expanduser()
    if token_cache == DEFAULT_TOKEN_CACHE:
        token_cache = account_config.account_token_cache_path(DEFAULT_TOKEN_CACHE, account)
    args.token_cache = token_cache

    content_html = str(manifest.get("content_html", ""))
    validation = validate_manifest(manifest, content_html)

    result: dict[str, Any] = {
        "manifest": str(args.manifest),
        "dry_run": dry_run,
        "env_file": str(env_file.resolve()) if env_file and env_file.exists() else "",
        "account": {
            "selector": account.get("selector", ""),
            "alias": account.get("alias", ""),
            "name": account.get("name", ""),
        },
        "token_cache": str(args.token_cache),
        "validation": validation,
    }
    issue_metadata = manifest_original_issue(manifest)
    if issue_metadata is not None:
        result["original_issue_policy"] = {
            "policy": manifest_original_issue_policy(manifest),
            "issue": issue_metadata[2],
        }
    if dry_run:
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
        write_json(out, result)
    elif args.resume:
        result = resume_publish_run(args, out, manifest, config, env_file, account, validation)
    else:
        result = create_publish_run(
            args,
            out,
            manifest,
            result,
            config,
            env_file,
            account,
            content_html,
            validation,
        )
    if result.get("status") == "success" and result.get("draft_media_id"):
        result["platform_workbench_update"] = sync_platform_images_to_workbench(
            manifest,
            result,
            out,
        )
        write_json(out, result)
    print(f"Wrote {out}")
    if result.get("draft_media_id"):
        print(f"Created draft media_id: {result['draft_media_id']}")
    if result.get("preview"):
        print("Preview sent.")


if __name__ == "__main__":
    main()
