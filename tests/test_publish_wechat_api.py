#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "wechat-article-pipeline" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import publish_wechat_api as publisher  # noqa: E402


PNG_1X1 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lpI1GQAAAABJRU5ErkJggg=="


class PublishWechatApiTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
