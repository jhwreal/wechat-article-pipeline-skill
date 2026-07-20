#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "wechat-article-pipeline" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import publish_wechat_api as publisher  # noqa: E402


PNG_1X1 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lpI1GQAAAABJRU5ErkJggg=="


class PublishWechatApiTest(unittest.TestCase):
    @staticmethod
    def valid_manifest() -> dict[str, Any]:
        return {
            "title": "测试标题",
            "digest": "测试摘要",
            "content_html": f'<p style="margin:0"><img src="{PNG_1X1}"></p>',
            "cover": {"src": PNG_1X1},
        }

    def test_body_image_compression_targets_900kb_upload_margin(self) -> None:
        self.assertEqual(publisher.MAX_BODY_IMAGE_BYTES, 1024 * 1024)
        self.assertEqual(publisher.BODY_IMAGE_TARGET_BYTES, 900 * 1024)
        self.assertLess(publisher.BODY_IMAGE_TARGET_BYTES, publisher.MAX_BODY_IMAGE_BYTES)

    def test_upload_body_images_removes_temporary_decoded_file(self) -> None:
        uploaded_paths: list[Path] = []
        original_api_post_multipart = publisher.api_post_multipart

        def fake_api_post_multipart(
            path: str,
            fields: dict[str, str],
            files: dict[str, publisher.LocalImage],
            access_token: str,
        ) -> dict[str, Any]:
            image = files["media"]
            self.assertTrue(image.path.exists())
            uploaded_paths.append(image.path)
            return {"url": "https://mmbiz.qpic.cn/body.png"}

        publisher.api_post_multipart = fake_api_post_multipart
        try:
            html, uploads = publisher.upload_body_images(f'<p><img src="{PNG_1X1}"></p>', "token")
        finally:
            publisher.api_post_multipart = original_api_post_multipart

        self.assertIn("https://mmbiz.qpic.cn/body.png", html)
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0]["local_path_removed"], "true")
        self.assertTrue(uploaded_paths)
        self.assertFalse(uploaded_paths[0].exists())

    def test_upload_cover_removes_temporary_decoded_file(self) -> None:
        uploaded_paths: list[Path] = []
        original_api_post_multipart = publisher.api_post_multipart

        def fake_api_post_multipart(
            path: str,
            fields: dict[str, str],
            files: dict[str, publisher.LocalImage],
            access_token: str,
        ) -> dict[str, Any]:
            image = files["media"]
            self.assertTrue(image.path.exists())
            uploaded_paths.append(image.path)
            return {"media_id": "thumb-id", "url": "https://mmbiz.qpic.cn/cover.png"}

        publisher.api_post_multipart = fake_api_post_multipart
        try:
            result = publisher.upload_cover({"cover": {"src": PNG_1X1}}, "token")
        finally:
            publisher.api_post_multipart = original_api_post_multipart

        self.assertEqual(result["thumb_media_id"], "thumb-id")
        self.assertEqual(result["local_path_removed"], "true")
        self.assertTrue(uploaded_paths)
        self.assertFalse(uploaded_paths[0].exists())

    def test_validate_manifest_rejects_non_embedded_body_images(self) -> None:
        manifest = self.valid_manifest()
        content_html = '<p style="margin:0"><img src="https://example.com/tracker.png"></p>'

        with self.assertRaisesRegex(SystemExit, "must be embedded data:image"):
            publisher.validate_manifest(manifest, content_html)

    def test_validate_manifest_rejects_unquoted_or_missing_image_src(self) -> None:
        manifest = self.valid_manifest()
        for content_html in (
            f"<p><img src={PNG_1X1}></p>",
            "<p><img alt=\"missing\"></p>",
        ):
            with self.subTest(content_html=content_html), self.assertRaisesRegex(
                SystemExit, "quoted src"
            ):
                publisher.validate_manifest(manifest, content_html)

    def test_body_image_uploader_accepts_whitespace_around_src_equals(self) -> None:
        original_api_post_multipart = publisher.api_post_multipart
        publisher.api_post_multipart = lambda *_args, **_kwargs: {
            "url": "https://mmbiz.qpic.cn/body.png"
        }
        try:
            html, uploads = publisher.upload_body_images(
                f'<p><img src = "{PNG_1X1}"></p>', "token"
            )
        finally:
            publisher.api_post_multipart = original_api_post_multipart

        self.assertIn('src="https://mmbiz.qpic.cn/body.png"', html)
        self.assertEqual(len(uploads), 1)

    def test_validate_manifest_rejects_malformed_data_image_payload(self) -> None:
        manifest = self.valid_manifest()
        manifest["cover"] = {"src": "data:image/png;base64,not-valid***"}

        with self.assertRaisesRegex(SystemExit, "malformed base64"):
            publisher.validate_manifest(manifest, "<p>正文。</p>")

    def test_validate_manifest_rejects_non_image_and_mismatched_image_payloads(self) -> None:
        manifest = self.valid_manifest()
        manifest["cover"] = {"src": "data:image/png;base64,aGVsbG8="}
        with self.assertRaisesRegex(SystemExit, "not a recognized image"):
            publisher.validate_manifest(manifest, "<p>正文。</p>")

        manifest["cover"] = {"src": PNG_1X1.replace("image/png", "image/jpeg")}
        with self.assertRaisesRegex(SystemExit, "does not match"):
            publisher.validate_manifest(manifest, "<p>正文。</p>")

    def test_validate_manifest_rejects_active_html_and_unsafe_links(self) -> None:
        manifest = self.valid_manifest()
        for content_html in (
            '<p onclick="alert(1)">正文。</p>',
            '<p><a href="java&#x73;cript:evil">点击</a></p>',
            '<p style="background:url(javascript:evil)">正文。</p>',
            '<script>alert(1)</script>',
        ):
            with self.subTest(content_html=content_html), self.assertRaisesRegex(
                SystemExit, "unsafe or malformed"
            ):
                publisher.validate_manifest(manifest, content_html)

    def test_url_safety_checks_only_the_header_without_missing_obfuscated_schemes(self) -> None:
        self.assertFalse(publisher._safe_draft_url("java\tscript:evil", image=False))
        self.assertFalse(publisher._safe_draft_url("data:text/html,evil", image=True))
        self.assertTrue(publisher._safe_draft_url("https://example.com/path", image=False))
        self.assertTrue(publisher._safe_draft_url(PNG_1X1, image=True))

    def test_validated_image_payload_is_shortened_before_structural_html_parse(self) -> None:
        manifest = self.valid_manifest()
        captured: list[str] = []
        original = publisher.validate_draft_html_safety

        def capture(content_html: str) -> None:
            captured.append(content_html)
            original(content_html)

        publisher.validate_draft_html_safety = capture
        try:
            validation = publisher.validate_manifest(manifest, manifest["content_html"])
        finally:
            publisher.validate_draft_html_safety = original

        self.assertEqual(validation["body_data_image_count"], 1)
        self.assertEqual(len(captured), 1)
        self.assertNotIn(PNG_1X1, captured[0])
        self.assertIn("data:image/png;base64,AA==", captured[0])

    def test_validate_manifest_rejects_failed_or_malformed_source_state(self) -> None:
        manifest = self.valid_manifest()
        manifest["source_state"] = {
            "core_revision": 2,
            "manifest_revision": 2,
            "asset_state": "failed",
            "stale_visuals": [],
            "missing_visuals": [],
        }
        with self.assertRaisesRegex(SystemExit, "not ready"):
            publisher.validate_manifest(manifest, "<p>正文。</p>")

        manifest["source_state"] = {"asset_state": "ready"}
        with self.assertRaisesRegex(SystemExit, "core_revision"):
            publisher.validate_manifest(manifest, "<p>正文。</p>")

    def test_verify_draft_raises_when_title_does_not_match(self) -> None:
        original_api_post_json = publisher.api_post_json
        publisher.api_post_json = lambda *_args, **_kwargs: {
            "news_item": [{"title": "另一个标题"}]
        }
        try:
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                publisher.verify_draft("media-id", "预期标题", "token")
        finally:
            publisher.api_post_json = original_api_post_json

    def test_verify_draft_raises_when_wechat_returns_no_articles(self) -> None:
        original_api_post_json = publisher.api_post_json
        publisher.api_post_json = lambda *_args, **_kwargs: {"news_item": []}
        try:
            with self.assertRaisesRegex(RuntimeError, "no article items"):
                publisher.verify_draft("media-id", "预期标题", "token")
        finally:
            publisher.api_post_json = original_api_post_json

    def test_open_draft_switch_implies_switch_check(self) -> None:
        args = SimpleNamespace(
            dry_run=False,
            create_draft=True,
            retry_preview=False,
            resume=False,
            out=Path("result.json"),
            check_draft_switch=False,
            open_draft_switch=True,
            verify_draft=False,
            send_preview=False,
            increment_original_issue=False,
            force_refresh_token=False,
        )

        self.assertFalse(publisher.validate_execution_mode(args))
        self.assertTrue(args.check_draft_switch)


if __name__ == "__main__":
    unittest.main()
