#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "wechat-article-pipeline" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import package_wechat_article_bundle as packager  # noqa: E402
import make_wechat_publish_manifest as manifest_builder  # noqa: E402
import verify_wechat_article_package as verifier  # noqa: E402
import build_wechat_article_workbench as builder  # noqa: E402


PNG_1X1 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lpI1GQAAAABJRU5ErkJggg=="


class PackageWechatArticleBundleTest(unittest.TestCase):
    def test_default_env_file_lives_in_skill_directory(self) -> None:
        expected = ROOT / "wechat-article-pipeline" / ".env"

        self.assertEqual(packager.DEFAULT_ENV_FILE, expected)
        self.assertEqual(manifest_builder.DEFAULT_ENV_FILE, expected)

    def test_image_size_reads_png_without_sips(self) -> None:
        original_run = packager.subprocess.run

        def unavailable_sips(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            raise FileNotFoundError("sips")

        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "one.png"
            image_path.write_bytes(base64.b64decode(PNG_1X1))
            packager.subprocess.run = unavailable_sips
            try:
                self.assertEqual(packager.image_size(image_path), (1, 1))
            finally:
                packager.subprocess.run = original_run

    def test_package_without_images_accepts_plain_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            article = root / "article.md"
            out = root / "article.html"
            article.write_text("# 标题\n\n正文第一段。\n", encoding="utf-8")
            old_argv = sys.argv
            sys.argv = [
                "package_wechat_article_bundle.py",
                str(article),
                str(out),
                "--no-images",
                "--no-publish-manifest",
            ]
            try:
                packager.main()
            finally:
                sys.argv = old_argv

            self.assertTrue(out.exists())
            html = out.read_text(encoding="utf-8")
            self.assertIn("正文第一段", html)
            self.assertNotIn("{{visual:", html)

    def test_workbench_markdown_uses_relative_image_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            files_dir = root / "files"
            images_dir = root / "image" / "article"
            files_dir.mkdir()
            images_dir.mkdir(parents=True)
            article = files_dir / "article.md"
            out = files_dir / "article.html"
            cover = images_dir / "cover.png"
            article.write_text("# 标题\n\n![题图]({{visual:cover}})\n\n正文第一段。\n", encoding="utf-8")
            cover.write_bytes(base64.b64decode(PNG_1X1))
            old_argv = sys.argv
            sys.argv = [
                "package_wechat_article_bundle.py",
                str(article),
                str(out),
                "--images-dir",
                str(images_dir),
                "--no-publish-manifest",
            ]
            try:
                packager.main()
            finally:
                sys.argv = old_argv

            html = out.read_text(encoding="utf-8")
            report = verifier.verify_package(out, images_dir=images_dir)

            self.assertIn("![题图](../image/article/cover.png)", html)
            self.assertNotIn("data:image/", html)
            self.assertEqual(report["status"], "ok")

    def test_direct_workbench_materializes_inline_visuals_as_relative_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            files_dir = root / "files"
            files_dir.mkdir()
            job = root / "article.job.json"
            out = files_dir / "article.html"
            data_uri = f"data:image/png;base64,{PNG_1X1}"
            job.write_text(
                json.dumps(
                    {
                        "article_markdown": "# 标题\n\n![题图]({{visual:cover}})\n\n正文第一段。\n",
                        "visuals": {"cover": {"data_uri": data_uri}},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            old_argv = sys.argv
            sys.argv = ["build_wechat_article_workbench.py", str(job), str(out)]
            try:
                builder.main()
            finally:
                sys.argv = old_argv

            html = out.read_text(encoding="utf-8")
            sidecar = out.with_name("article.clipboard-assets.js").read_text(encoding="utf-8")

            self.assertTrue((files_dir / "article.assets" / "cover.png").exists())
            self.assertIn("![题图](article.assets/cover.png)", html)
            self.assertIn("article.clipboard-assets.js", html)
            self.assertNotIn(data_uri, html)
            self.assertIn(data_uri, sidecar)

    def test_workbench_uses_relative_paths_while_publish_manifest_embeds_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            files_dir = root / "files"
            images_dir = root / "image" / "article"
            files_dir.mkdir()
            images_dir.mkdir(parents=True)
            article = files_dir / "article.md"
            out = files_dir / "article.html"
            cover = images_dir / "cover.png"
            article.write_text("# 标题\n\n![题图]({{visual:cover}})\n\n正文第一段。\n", encoding="utf-8")
            cover.write_bytes(base64.b64decode(PNG_1X1))
            old_argv = sys.argv
            sys.argv = [
                "package_wechat_article_bundle.py",
                str(article),
                str(out),
                "--images-dir",
                str(images_dir),
                "--author",
                "作者",
                "--publisher-env-file",
                str(root / "empty.env"),
            ]
            try:
                packager.main()
            finally:
                sys.argv = old_argv

            html = out.read_text(encoding="utf-8")
            clipboard_assets = out.with_name("article.clipboard-assets.js").read_text(encoding="utf-8")
            manifest = json.loads(out.with_suffix(".publish-manifest.json").read_text(encoding="utf-8"))
            report = verifier.verify_package(out, images_dir=images_dir)

            self.assertIn("![题图](../image/article/cover.png)", html)
            self.assertIn("article.clipboard-assets.js", html)
            self.assertNotIn("data:image/", html)
            self.assertIn("WECHAT_CLIPBOARD_IMAGE_DATA", clipboard_assets)
            self.assertIn("../image/article/cover.png", clipboard_assets)
            self.assertIn("data:image/png;base64,", clipboard_assets)
            self.assertIn('src="data:image/png;base64,', manifest["content_html"])
            self.assertTrue(manifest["cover"]["src"].startswith("data:image/png;base64,"))
            self.assertTrue(manifest["image_candidates"][0]["src"].startswith("data:image/png;base64,"))
            self.assertEqual(report["status"], "ok")

    def test_no_image_publish_manifest_requires_explicit_cover(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            article = root / "article.md"
            out = root / "article.html"
            article.write_text("# 标题\n\n正文第一段。\n", encoding="utf-8")
            old_argv = sys.argv
            sys.argv = [
                "package_wechat_article_bundle.py",
                str(article),
                str(out),
                "--no-images",
                "--author",
                "作者",
                "--publisher-env-file",
                str(root / "empty.env"),
            ]
            try:
                with self.assertRaises(SystemExit) as raised:
                    packager.main()
            finally:
                sys.argv = old_argv

            self.assertIn("--cover-image", str(raised.exception))

    def test_no_image_publish_manifest_uses_explicit_cover_without_body_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            article = root / "article.md"
            out = root / "article.html"
            cover = root / "cover.png"
            images_dir = root / "images"
            article.write_text("# 标题\n\n正文第一段。\n", encoding="utf-8")
            cover.write_bytes(base64.b64decode(PNG_1X1))
            old_argv = sys.argv
            sys.argv = [
                "package_wechat_article_bundle.py",
                str(article),
                str(out),
                "--no-images",
                "--cover-image",
                str(cover),
                "--images-dir",
                str(images_dir),
                "--author",
                "作者",
                "--publisher-env-file",
                str(root / "empty.env"),
            ]
            try:
                packager.main()
            finally:
                sys.argv = old_argv

            manifest = json.loads(out.with_suffix(".publish-manifest.json").read_text(encoding="utf-8"))
            job = json.loads(out.with_suffix(".job.json").read_text(encoding="utf-8"))

            self.assertEqual(job["visuals"]["cover"]["role"], "api_cover")
            self.assertEqual(manifest["cover"]["name"], "cover")
            self.assertTrue(manifest["cover"]["src"].startswith("data:image/png;base64,"))
            self.assertEqual(manifest["image_candidates"][0]["name"], "cover")
            self.assertNotIn("data:image/", manifest["content_html"])
            self.assertIn("pic_crop_235_1", manifest["wechat_cover"]["crop_values"])


if __name__ == "__main__":
    unittest.main()
