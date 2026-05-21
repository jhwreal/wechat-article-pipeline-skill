#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import re
import secrets
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_API_CONFIG = Path.home() / ".codex" / "wechat-article-pipeline" / "wechat-api-config.json"
API_BASE = "https://api.weixin.qq.com"
DATA_IMAGE_RE = re.compile(r'src=(["\'])(data:image/[^"\']+)\1', re.I)
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a WeChat Official Account draft from publish-manifest.json via official APIs."
    )
    parser.add_argument("manifest", type=Path, help="publish-manifest.json from package_wechat_article_bundle.py.")
    parser.add_argument("--config", type=Path, default=DEFAULT_API_CONFIG, help="Local API config path.")
    parser.add_argument("--appid", help="WeChat Official Account AppID. Stored only when --remember is set.")
    parser.add_argument("--appsecret", help="WeChat Official Account AppSecret. Stored only when --remember is set.")
    parser.add_argument("--access-token", help="Use an existing access_token instead of fetching one.")
    parser.add_argument("--force-refresh-token", action="store_true", help="Force refresh stable access_token.")
    parser.add_argument("--remember", action="store_true", help="Persist appid/appsecret and token cache to local config.")
    parser.add_argument("--check-draft-switch", action="store_true", help="Check draft switch state before creating a draft.")
    parser.add_argument("--open-draft-switch", action="store_true", help="Open the draft switch if WeChat reports it closed.")
    parser.add_argument("--send-preview", action="store_true", help="Send a preview after the draft is created.")
    parser.add_argument("--preview-account", help="Preview target WeChat ID. Overrides manifest preview.account.")
    parser.add_argument("--preview-openid", help="Preview target OpenID. Takes precedence over WeChat ID.")
    parser.add_argument("--content-source-url", default="", help="Optional original/source URL for the article.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and write the draft request payload without API calls.")
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


def save_config(path: Path, config: dict[str, Any]) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


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


def get_access_token(args: argparse.Namespace, config: dict[str, Any]) -> str:
    if args.access_token:
        return args.access_token.strip()

    cached = config.get("access_token_cache") or {}
    if not args.force_refresh_token and cached.get("access_token") and float(cached.get("expires_at", 0)) > time.time() + 300:
        return str(cached["access_token"])

    appid = (args.appid or config.get("appid") or "").strip()
    appsecret = (args.appsecret or config.get("appsecret") or "").strip()
    if not appid or not appsecret:
        raise SystemExit(
            "Missing AppID/AppSecret. Pass --appid and --appsecret, or store them in "
            f"{args.config.expanduser()}."
        )

    payload: dict[str, Any] = {"grant_type": "client_credential", "appid": appid, "secret": appsecret}
    if args.force_refresh_token:
        payload["force_refresh"] = True
    token_resp = api_post_json("/cgi-bin/stable_token", payload)
    token = str(token_resp["access_token"])
    expires_in = int(token_resp.get("expires_in", 7200))
    if args.remember:
        config["appid"] = appid
        config["appsecret"] = appsecret
        config["access_token_cache"] = {"access_token": token, "expires_at": int(time.time()) + expires_in}
        save_config(args.config, config)
    return token


def decode_data_image(data_uri: str, suffix_hint: str) -> LocalImage:
    header, encoded = data_uri.split(",", 1)
    mime = header[5:].split(";")[0].lower()
    raw = base64.b64decode(encoded)
    suffix = mimetypes.guess_extension(mime) or f".{suffix_hint}"
    tmp = tempfile.NamedTemporaryFile(prefix="wechat-image-", suffix=suffix, delete=False)
    tmp.write(raw)
    tmp.close()
    return LocalImage(Path(tmp.name), mime)


def normalize_body_image(image: LocalImage) -> LocalImage:
    allowed = {"image/jpeg", "image/png"}
    if image.mime in allowed and image.path.stat().st_size <= 1024 * 1024:
        return image
    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover - optional dependency
        raise SystemExit(
            f"Body image {image.path} is {image.mime} or larger than 1MB. "
            "Install Pillow or provide jpg/png body images under 1MB."
        ) from exc
    with Image.open(image.path) as img:
        img = img.convert("RGB")
        max_side = max(img.size)
        if max_side > 1400:
            ratio = 1400 / max_side
            img = img.resize((int(img.width * ratio), int(img.height * ratio)))
        out = tempfile.NamedTemporaryFile(prefix="wechat-body-", suffix=".jpg", delete=False)
        quality = 88
        while quality >= 55:
            img.save(out.name, "JPEG", quality=quality, optimize=True)
            if Path(out.name).stat().st_size <= 1024 * 1024:
                return LocalImage(Path(out.name), "image/jpeg")
            quality -= 8
    raise SystemExit(f"Could not compress body image {image.path} under 1MB.")


def upload_body_images(content_html: str, access_token: str) -> tuple[str, list[dict[str, str]]]:
    uploads: list[dict[str, str]] = []

    def replace(match: re.Match[str]) -> str:
        quote = match.group(1)
        data_uri = match.group(2)
        image = normalize_body_image(decode_data_image(data_uri, "png"))
        resp = api_post_multipart("/cgi-bin/media/uploadimg", {}, {"media": image}, access_token)
        url = str(resp["url"])
        uploads.append({"kind": "body", "local_path": str(image.path), "url": url})
        return f"src={quote}{url}{quote}"

    return DATA_IMAGE_RE.sub(replace, content_html), uploads


def upload_cover(manifest: dict[str, Any], access_token: str) -> dict[str, str]:
    cover = manifest.get("cover") or {}
    src = str(cover.get("src") or "").strip()
    if not src.startswith("data:image/"):
        raise SystemExit("Manifest cover.src must be a data:image URI for API publishing.")
    image = decode_data_image(src, "png")
    resp = api_post_multipart("/cgi-bin/material/add_material?type=image", {}, {"media": image}, access_token)
    return {
        "thumb_media_id": str(resp["media_id"]),
        "url": str(resp.get("url", "")),
        "local_path": str(image.path),
    }


def default_crop_values() -> dict[str, str]:
    return {
        "pic_crop_235_1": "0_0.287234_1_0.712766",
        "pic_crop_1_1": "0.21875_0_0.78125_1",
    }


def build_draft_payload(
    manifest: dict[str, Any],
    content_html: str,
    thumb_media_id: str,
    content_source_url: str,
) -> dict[str, Any]:
    title = str(manifest.get("title", "")).strip()
    if not title:
        raise SystemExit("Manifest title is empty.")
    author = str(manifest.get("author", "")).strip()
    digest = str(manifest.get("digest", "")).strip()[:120]
    article: dict[str, Any] = {
        "article_type": "news",
        "title": title,
        "author": author,
        "digest": digest,
        "content": content_html,
        "content_source_url": content_source_url,
        "thumb_media_id": thumb_media_id,
        "need_open_comment": 0,
        "only_fans_can_comment": 0,
        **default_crop_values(),
    }
    return {"articles": [article]}


def check_or_open_draft_switch(access_token: str, open_switch: bool) -> dict[str, Any]:
    resp = api_post_json("/cgi-bin/draft/switch?checkonly=1", {}, access_token)
    if resp.get("is_open") == 0 and open_switch:
        resp = api_post_json("/cgi-bin/draft/switch", {}, access_token)
    return resp


def create_draft(payload: dict[str, Any], access_token: str) -> str:
    resp = api_post_json("/cgi-bin/draft/add", payload, access_token)
    return str(resp["media_id"])


def send_preview(media_id: str, args: argparse.Namespace, manifest: dict[str, Any], access_token: str) -> dict[str, Any]:
    preview = manifest.get("preview") or {}
    payload: dict[str, Any] = {"mpnews": {"media_id": media_id}, "msgtype": "mpnews"}
    if args.preview_openid:
        payload["touser"] = args.preview_openid.strip()
    else:
        account = (args.preview_account or preview.get("account") or "").strip()
        if not account:
            raise SystemExit("Preview account is empty. Pass --preview-account or set manifest.preview.account.")
        payload["towxname"] = account
    return api_post_json("/cgi-bin/message/mass/preview", payload, access_token)


def main() -> None:
    args = parse_args()
    manifest = read_json(args.manifest.resolve())
    config = read_config(args.config)

    content_html = str(manifest.get("content_html", ""))
    if not content_html:
        raise SystemExit("Manifest content_html is empty.")

    result: dict[str, Any] = {"manifest": str(args.manifest.resolve()), "dry_run": args.dry_run}
    draft_payload: dict[str, Any]

    if args.dry_run:
        draft_payload = build_draft_payload(manifest, content_html, "DRY_RUN_THUMB_MEDIA_ID", args.content_source_url)
        result["draft_payload"] = draft_payload
    else:
        access_token = get_access_token(args, config)
        if args.check_draft_switch:
            result["draft_switch"] = check_or_open_draft_switch(access_token, args.open_draft_switch)
        uploaded_content_html, body_uploads = upload_body_images(content_html, access_token)
        cover_upload = upload_cover(manifest, access_token)
        draft_payload = build_draft_payload(
            manifest,
            uploaded_content_html,
            cover_upload["thumb_media_id"],
            args.content_source_url,
        )
        media_id = create_draft(draft_payload, access_token)
        result.update(
            {
                "body_uploads": body_uploads,
                "cover_upload": cover_upload,
                "draft_payload": draft_payload,
                "draft_media_id": media_id,
            }
        )
        if args.send_preview:
            result["preview"] = send_preview(media_id, args, manifest, access_token)

    out = (args.out or args.manifest.with_suffix(".wechat-api-result.json")).resolve()
    write_json(out, result)
    print(f"Wrote {out}")
    if result.get("draft_media_id"):
        print(f"Created draft media_id: {result['draft_media_id']}")
    if result.get("preview"):
        print("Preview sent.")


if __name__ == "__main__":
    main()
