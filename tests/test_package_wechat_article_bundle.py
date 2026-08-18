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
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "wechat-article-pipeline" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import package_wechat_article_bundle as packager  # noqa: E402
import make_wechat_publish_manifest as manifest_builder  # noqa: E402
import verify_wechat_article_package as verifier  # noqa: E402
import build_wechat_article_workbench as builder  # noqa: E402


PNG_1X1 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR42mNk+M/wHwAF/gL+IpcQ3wAAAABJRU5ErkJggg=="


class PackageWechatArticleBundleTest(unittest.TestCase):
    def test_workbench_discovers_wechat_hosted_images_for_platform_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            job_path = root / "article.job.json"
            out = root / "article.html"
            job_path.write_text(
                json.dumps(
                    {
                        "article_markdown": "# 标题\n\n![题图](https://example.com/local.png)\n",
                        "visuals": {},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            receipt = root / "article.publish-manifest.wechat-api-result.json"
            receipt.write_text(
                json.dumps(
                    {
                        "status": "success",
                        "body_uploads": [
                            {"kind": "body", "url": "http://mmbiz.qpic.cn/body.png?from=appmsg"}
                        ],
                    }
                ),
                encoding="utf-8",
            )

            old_argv = sys.argv
            sys.argv = ["build_wechat_article_workbench.py", str(job_path), str(out)]
            try:
                builder.main()
            finally:
                sys.argv = old_argv

            bootstrap = builder.read_bootstrap(out.read_text(encoding="utf-8"))
            self.assertEqual(
                bootstrap["platformImageUrls"],
                ["https://mmbiz.qpic.cn/body.png?from=appmsg"],
            )
            self.assertEqual(bootstrap["platformImageSource"], str(receipt.resolve()))
            self.assertEqual(bootstrap["buildInfo"]["skillVersion"], "1.7.0")
            self.assertEqual(bootstrap["buildInfo"]["workbenchSchemaVersion"], 3)
            self.assertEqual(
                set(bootstrap["platformAdapters"]),
                {"wechat", "toutiao", "xiaohongshu"},
            )

    def test_platform_image_url_normalization_rejects_non_https_hosts(self) -> None:
        self.assertEqual(
            builder.normalize_platform_image_url("http://mmbiz.qpic.cn/body.png"),
            "https://mmbiz.qpic.cn/body.png",
        )
        self.assertEqual(builder.normalize_platform_image_url("http://example.com/body.png"), "")
        self.assertEqual(builder.normalize_platform_image_url("data:image/png;base64,abc"), "")

    def test_verifier_requires_the_exact_planned_image_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            html = root / "article.html"
            images = root / "images"
            image_jobs = root / "article.image-jobs.json"
            images.mkdir()
            html.write_text("<html>article</html>", encoding="utf-8")
            (images / "diagram.png").write_bytes(base64.b64decode(PNG_1X1))
            image_jobs.write_text(
                json.dumps(
                    {
                        "kind": "wechat-image-jobs",
                        "schema_version": 2,
                        "article": {},
                        "rules": {},
                        "review_defaults": {},
                        "slots": [{"name": "diagram", "output": "diagram.webp"}],
                        "generation_queue": [
                            {
                                "slot": "diagram",
                                "output": "diagram.webp",
                                "generation_prompt": "diagram",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            report = verifier.verify_package(
                html, image_jobs_path=image_jobs, images_dir=images
            )

            output_check = next(
                item for item in report["checks"] if item["name"] == "image_jobs_outputs_exist"
            )
            self.assertFalse(output_check["ok"])
            self.assertIn("diagram.webp", output_check["detail"])

    def test_verifier_reports_invalid_job_and_manifest_json_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            html = root / "article.html"
            job = root / "article.job.json"
            manifest = root / "article.publish-manifest.json"
            html.write_text("<html>article</html>", encoding="utf-8")
            job.write_text("{broken", encoding="utf-8")
            manifest.write_text("[]", encoding="utf-8")

            report = verifier.verify_package(
                html,
                job_path=job,
                manifest_path=manifest,
                require_manifest=True,
            )

            self.assertEqual(report["status"], "failed")
            self.assertTrue(
                any(item["name"] == "job_valid" and not item["ok"] for item in report["checks"])
            )
            self.assertTrue(
                any(
                    item["name"] == "manifest_json_valid" and not item["ok"]
                    for item in report["checks"]
                )
            )

    def test_verifier_detects_manifest_staleness_after_source_asset_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            html = root / "article.html"
            job_path = root / "article.job.json"
            manifest_path = root / "article.publish-manifest.json"
            cover = root / "cover.png"
            html.write_text("<html>article</html>", encoding="utf-8")
            cover.write_bytes(base64.b64decode(PNG_1X1))
            job = {
                "article_markdown": "# 标题\n\n正文。",
                "visuals": {"cover": {"path": str(cover)}},
            }
            job_path.write_text(json.dumps(job), encoding="utf-8")
            manifest = {
                "title": "标题",
                "digest": "摘要",
                "content_html": "<p>正文。</p>",
                "cover": {"src": f"data:image/png;base64,{PNG_1X1}"},
                "workbench_html": str(html),
                "source_fingerprint": manifest_builder.compute_source_fingerprint(
                    job, root
                ),
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            initial = verifier.verify_package(
                html, job_path=job_path, manifest_path=manifest_path
            )
            cover.write_bytes(base64.b64decode(PNG_1X1) + b"changed")
            stale = verifier.verify_package(
                html, job_path=job_path, manifest_path=manifest_path
            )

            self.assertEqual(initial["status"], "ok")
            match_check = next(
                item
                for item in stale["checks"]
                if item["name"] == "manifest_source_matches_job"
            )
            self.assertFalse(match_check["ok"])
            self.assertEqual(stale["status"], "failed")

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

    def test_center_crop_does_not_hide_corrupt_images_behind_sips(self) -> None:
        with mock.patch.object(
            packager,
            "write_center_crop_with_pillow",
            side_effect=OSError("broken image"),
        ), mock.patch.object(packager, "write_center_crop_with_sips") as sips:
            with self.assertRaisesRegex(OSError, "broken image"):
                packager.write_center_crop(
                    Path("broken.png"), Path("out.png"), (0, 0, 1, 1), 1, 1
                )

        sips.assert_not_called()

    def test_center_crop_uses_sips_only_when_pillow_is_unavailable(self) -> None:
        with mock.patch.object(
            packager,
            "write_center_crop_with_pillow",
            side_effect=ModuleNotFoundError("Pillow is unavailable"),
        ), mock.patch.object(packager, "write_center_crop_with_sips") as sips:
            packager.write_center_crop(
                Path("source.png"), Path("out.png"), (0, 0, 1, 1), 1, 1
            )

        sips.assert_called_once()

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
            ]
            try:
                packager.main()
            finally:
                sys.argv = old_argv

            self.assertTrue(out.exists())
            html = out.read_text(encoding="utf-8")
            self.assertIn("正文第一段", html)
            self.assertNotIn("{{visual:", html)
            self.assertFalse(out.with_suffix(".publish-manifest.json").exists())

    def test_no_image_packaging_removes_existing_visual_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            article = root / "article.md"
            out = root / "article.html"
            article.write_text(
                "# 标题\n\n![题图]({{visual:cover}})\n\n正文。\n\n"
                "![配图]({{visual:body-1}})\n\n![尾图]({{visual:closing}})\n",
                encoding="utf-8",
            )
            old_argv = sys.argv
            sys.argv = [
                "package_wechat_article_bundle.py",
                str(article),
                str(out),
                "--no-images",
            ]
            try:
                packager.main()
            finally:
                sys.argv = old_argv

            html = out.read_text(encoding="utf-8")
            job = json.loads(out.with_suffix(".job.json").read_text(encoding="utf-8"))

            self.assertNotIn("{{visual:", html)
            self.assertNotIn("{{visual:", job["article_markdown"])
            self.assertEqual(job["visuals"], {})

    def test_explicit_signature_bypasses_ambiguous_saved_signatures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            article = root / "article.md"
            out = root / "article.html"
            env_file = root / ".env"
            article.write_text("# 标题\n\n正文第一段。\n", encoding="utf-8")
            env_file.write_text(
                "WECHAT_SIGNATURE_AUTHOR=默认作者\n"
                "WECHAT_ORIGINAL_ISSUE=2\n"
                "WECHAT_ACCOUNT_SECOND_NAME=第二个号\n"
                "WECHAT_ACCOUNT_SECOND_SIGNATURE_AUTHOR=第二作者\n"
                "WECHAT_ACCOUNT_SECOND_ORIGINAL_ISSUE=5\n",
                encoding="utf-8",
            )
            old_argv = sys.argv
            sys.argv = [
                "package_wechat_article_bundle.py",
                str(article),
                str(out),
                "--no-images",
                "--publisher-env-file",
                str(env_file),
                "--signature-author",
                "明确作者",
                "--original-issue",
                "7",
            ]
            try:
                packager.main()
            finally:
                sys.argv = old_argv

            job = json.loads(out.with_suffix(".job.json").read_text(encoding="utf-8"))

            self.assertEqual(job["article_signature"]["author"], "明确作者")
            self.assertEqual(job["article_signature"]["issue"], 7)
            self.assertEqual(job["article_signature"]["account"]["alias"], "")

    def test_same_session_revision_reuses_previous_issue_without_changing_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            article = root / "article.md"
            out = root / "article.html"
            env_file = root / ".env"
            article.write_text("# 标题\n\n正文第一段。\n", encoding="utf-8")
            env_file.write_text(
                "WECHAT_SIGNATURE_AUTHOR=作者\nWECHAT_ORIGINAL_ISSUE=10\n",
                encoding="utf-8",
            )
            old_argv = sys.argv
            sys.argv = [
                "package_wechat_article_bundle.py",
                str(article),
                str(out),
                "--no-images",
                "--publisher-env-file",
                str(env_file),
                "--same-session-revision",
            ]
            try:
                packager.main()
            finally:
                sys.argv = old_argv

            job = json.loads(out.with_suffix(".job.json").read_text(encoding="utf-8"))
            env_text = env_file.read_text(encoding="utf-8")

        self.assertEqual(job["article_signature"]["issue"], 9)
        self.assertEqual(job["article_signature"]["label"], "作者的第9篇原创")
        self.assertEqual(job["article_signature"]["counter_policy"], "reuse_previous")
        self.assertIn("WECHAT_ORIGINAL_ISSUE=10", env_text)

    def test_same_session_revision_rejects_explicit_original_issue(self) -> None:
        with self.assertRaisesRegex(SystemExit, "cannot be combined"):
            packager.resolve_signature_metadata(
                env_file=Path(".env"),
                account={"signature_author": "作者", "original_issue": "10", "alias": "", "name": ""},
                signature_author=None,
                original_issue=9,
                same_session_revision=True,
            )

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

    def test_packager_uses_exact_output_filename_from_image_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            files_dir = root / "files"
            images_dir = root / "image" / "article"
            files_dir.mkdir()
            images_dir.mkdir(parents=True)
            article = files_dir / "article.md"
            out = files_dir / "article.html"
            plan = files_dir / "article.image-jobs.json"
            article.write_text(
                "# 标题\n\n![题图]({{visual:cover}})\n\n正文。\n", encoding="utf-8"
            )
            (images_dir / "hero-custom.png").write_bytes(base64.b64decode(PNG_1X1))
            plan.write_text(
                json.dumps(
                    {
                        "kind": "wechat-image-jobs",
                        "schema_version": 2,
                        "article": {"slug": "article"},
                        "rules": {},
                        "review_defaults": {},
                        "slots": [{"name": "cover", "output": "hero-custom.png"}],
                        "generation_queue": [
                            {
                                "slot": "cover",
                                "output": "hero-custom.png",
                                "generation_prompt": "cover",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            old_argv = sys.argv
            sys.argv = [
                "package_wechat_article_bundle.py",
                str(article),
                str(out),
                "--images-dir",
                str(images_dir),
                "--plan-json",
                str(plan),
            ]
            try:
                packager.main()
            finally:
                sys.argv = old_argv

            job = json.loads(out.with_suffix(".job.json").read_text(encoding="utf-8"))
            html = out.read_text(encoding="utf-8")

        self.assertTrue(job["visuals"]["cover"]["path"].endswith("hero-custom.png"))
        self.assertIn("![题图](../image/article/hero-custom.png)", html)

    def test_packager_removes_only_visuals_explicitly_skipped_by_fast_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            files_dir = root / "files"
            images_dir = root / "image" / "article"
            files_dir.mkdir()
            images_dir.mkdir(parents=True)
            article = files_dir / "article.md"
            out = files_dir / "article.html"
            plan = files_dir / "article.image-jobs.json"
            article.write_text(
                "# 标题\n\n"
                "![题图]({{visual:cover}})\n\n"
                "第一段。\n\n![配图1]({{visual:body-1}})\n\n"
                "第二段。\n\n![配图2]({{visual:body-2}})\n\n"
                "结尾。\n\n![尾图]({{visual:closing}})\n",
                encoding="utf-8",
            )
            for name in ("cover", "body-1", "closing"):
                (images_dir / f"{name}.png").write_bytes(base64.b64decode(PNG_1X1))
            slots = [
                {"name": name, "output": f"{name}.png"}
                for name in ("cover", "body-1", "closing")
            ]
            plan.write_text(
                json.dumps(
                    {
                        "kind": "wechat-image-jobs",
                        "schema_version": 2,
                        "article": {
                            "slug": "article",
                            "planning_mode": "fast",
                            "skipped_visuals": ["body-2"],
                        },
                        "rules": {},
                        "review_defaults": {},
                        "slots": slots,
                        "generation_queue": [
                            {
                                "slot": slot["name"],
                                "output": slot["output"],
                                "generation_prompt": slot["name"],
                            }
                            for slot in slots
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            old_argv = sys.argv
            sys.argv = [
                "package_wechat_article_bundle.py",
                str(article),
                str(out),
                "--images-dir",
                str(images_dir),
                "--plan-json",
                str(plan),
            ]
            try:
                packager.main()
            finally:
                sys.argv = old_argv

            html = out.read_text(encoding="utf-8")
            job = json.loads(out.with_suffix(".job.json").read_text(encoding="utf-8"))

            self.assertNotIn("{{visual:body-2}}", html)
            self.assertNotIn("配图2", html)
            self.assertNotIn("{{visual:body-2}}", job["article_markdown"])
            self.assertIn("{{visual:body-1}}", job["article_markdown"])

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
            self.assertNotIn('<script src="article.clipboard-assets.js">', html)
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
                "--publish-manifest",
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
            self.assertNotIn('<script src="article.clipboard-assets.js">', html)
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
                "--publish-manifest",
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
                "--publish-manifest",
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
