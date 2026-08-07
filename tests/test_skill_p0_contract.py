#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "wechat-article-pipeline"
SCRIPTS = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS))

import postprocess_wechat_article as postprocess  # noqa: E402


class SkillP0ContractTest(unittest.TestCase):
    def test_article_slug_cannot_escape_the_workspace_image_directory(self) -> None:
        self.assertEqual(postprocess.validate_article_slug("中文-slug"), "中文-slug")
        for slug in ("../outside", "nested/path", r"nested\path", ".", "", "CON", "bad:name"):
            with self.subTest(slug=slug), self.assertRaises(SystemExit):
                postprocess.validate_article_slug(slug)

    def test_installable_skill_contains_publisher_env_template(self) -> None:
        env_template = SKILL_DIR / ".env.example"

        self.assertTrue(env_template.exists())
        source = env_template.read_text(encoding="utf-8")
        self.assertIn("WECHAT_APPID=", source)
        self.assertIn("WECHAT_ACCOUNT_JUZI_NAME=", source)

    def test_skill_metadata_and_release_version_are_consistent(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "package-skill.yml").read_text(
            encoding="utf-8"
        )
        agent_metadata = (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")
        skill_version = (SKILL_DIR / "VERSION").read_text(encoding="utf-8").strip()

        version_match = re.search(r'^version = "([^"]+)"$', pyproject, re.M)
        self.assertIsNotNone(version_match)
        assert version_match is not None
        version = version_match.group(1)
        self.assertEqual(version, "1.6.1")
        self.assertEqual(skill_version, version)
        self.assertIn(f"V {version}（当前版本）", readme)
        self.assertIn(f"V {version} (current version)", readme)
        self.assertIn("PROJECT_VERSION", workflow)
        self.assertIn("agents/openai.yaml", workflow)
        self.assertIn('display_name: "微信公众号文章流水线"', agent_metadata)
        self.assertIn("$wechat-article-pipeline", agent_metadata)

    def test_platform_adapter_registry_is_the_workbench_rule_source(self) -> None:
        adapters = json.loads(
            (SKILL_DIR / "references" / "platform-adapters.json").read_text(encoding="utf-8")
        )
        self.assertEqual(adapters["schema_version"], 1)
        self.assertEqual(
            {name for name in adapters if name != "schema_version"},
            {"wechat", "toutiao", "xiaohongshu"},
        )
        self.assertEqual(adapters["toutiao"]["titleMax"], 30)
        self.assertEqual(adapters["xiaohongshu"]["titleMax"], 64)
        self.assertEqual(adapters["toutiao"]["headingMap"]["H3"], "H1")
        self.assertEqual(adapters["xiaohongshu"]["headingMap"]["H3"], "H2")

    def test_skill_md_stays_lean_and_trigger_description_is_not_a_workflow(self) -> None:
        skill_md = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        match = re.match(r"---\n(?P<frontmatter>.*?)\n---\n(?P<body>.*)", skill_md, re.S)
        self.assertIsNotNone(match)
        assert match is not None

        description_match = re.search(r'^description:\s*"?(.+?)"?$', match.group("frontmatter"), re.M)
        self.assertIsNotNone(description_match)
        assert description_match is not None
        description = description_match.group(1)

        self.assertTrue(description.startswith("Use when "))
        self.assertLessEqual(len(description), 500)
        for workflow_word in (
            "including",
            "article structure",
            "image generation",
            "uploads images",
            "workflow",
        ):
            self.assertNotIn(workflow_word, description)

        body = match.group("body")
        word_count = len(re.findall(r"[A-Za-z0-9_`./:-]+|[\u4e00-\u9fff]", body))
        self.assertGreaterEqual(word_count, 800)
        self.assertLessEqual(word_count, 1200)

    def test_skill_md_routes_to_main_entry_without_confirmation_conflict(self) -> None:
        skill_md = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("postprocess_wechat_article.py", skill_md)
        self.assertIn("--plan-only", skill_md)
        self.assertIn("--no-images", skill_md)
        self.assertIn("--missing-only", skill_md)
        for conflicting_phrase in (
            "After the user confirms",
            "after the user confirms",
            "article copy is approved",
            "Confirm the article copy",
        ):
            self.assertNotIn(conflicting_phrase, skill_md)

    def test_workbench_template_keeps_wechat_data_images_without_polluting_markdown(self) -> None:
        template = (SKILL_DIR / "assets" / "templates" / "wechat-md-workbench.template.v3.html").read_text(encoding="utf-8")

        self.assertIn("相对路径配图", template)
        self.assertIn("复制富文本", template)
        self.assertIn("CLIPBOARD_ASSETS_SCRIPT", template)
        self.assertIn("clipboardAssetsScript", template)
        self.assertIn("ensureClipboardAssetsLoaded", template)
        self.assertIn("releaseClipboardAssets", template)
        self.assertIn("WECHAT_CLIPBOARD_IMAGE_DATA", template)
        self.assertIn("copyRichHtmlForPlatform", template)
        self.assertIn("inlineImagesForClipboard", template)
        self.assertIn("imageToDataUri", template)
        self.assertIn("canvas.toDataURL", template)
        self.assertIn("ClipboardItem", template)
        self.assertIn("data:image", template)
        self.assertIn("? buildInlineWechatHtml()", template)
        self.assertIn("display:inline-block; max-width:100%; box-sizing:border-box", template)
        self.assertIn("文件保存功能加载失败", template)
        self.assertIn("persistenceWarning", template)
        self.assertIn("editor.readOnly = !enabled", template)
        self.assertIn("saveArticleButton.disabled = !enabled", template)
        self.assertIn("当前工作台是以本地文件方式打开的", template)
        self.assertIn("本地保存服务连接已经中断", template)
        for stale_phrase in (
            "单文件",
            "复制到公众号",
            "公众号可粘贴",
        ):
            self.assertNotIn(stale_phrase, template)

    def test_example_workbenches_keep_markdown_images_relative(self) -> None:
        examples_dir = ROOT / "examples"
        for html_path in (examples_dir / "method-article.html", examples_dir / "emotion-article.html"):
            html = html_path.read_text(encoding="utf-8")

            self.assertIn(f"{html_path.stem}.clipboard-assets.js", html)
            self.assertIn("![题图](assets/cover.svg)", html)
            self.assertNotIn("data:image/svg+xml;base64", html)
            self.assertNotIn("复制到公众号", html)

            sidecar = html_path.with_name(f"{html_path.stem}.clipboard-assets.js").read_text(encoding="utf-8")
            self.assertIn("WECHAT_CLIPBOARD_IMAGE_DATA", sidecar)
            self.assertIn("assets/cover.svg", sidecar)
            self.assertIn("data:image/svg+xml;base64", sidecar)

    def test_postprocess_no_images_skips_image_planning(self) -> None:
        commands: list[list[str]] = []

        def fake_run(command: list[str]) -> None:
            commands.append(command)

        original_run = postprocess.run
        try:
            postprocess.run = fake_run
            with tempfile.TemporaryDirectory() as tmp_dir:
                root = Path(tmp_dir)
                article = root / "article.md"
                out = root / "out.html"
                article.write_text("# 标题\n\n正文第一段。\n", encoding="utf-8")
                old_argv = sys.argv
                sys.argv = [
                    "postprocess_wechat_article.py",
                    str(article),
                    str(out),
                    "--no-images",
                ]
                try:
                    postprocess.main()
                finally:
                    sys.argv = old_argv
        finally:
            postprocess.run = original_run

        command_text = "\n".join(" ".join(command) for command in commands)
        self.assertIn("mark_wechat_article_focus.py", command_text)
        self.assertIn("package_wechat_article_bundle.py", command_text)
        self.assertIn("--no-images", command_text)
        self.assertNotIn("--publish-manifest", command_text)
        self.assertNotIn("make_wechat_article_image_jobs.py", command_text)

    def test_postprocess_no_images_publish_manifest_requires_cover(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            article = root / "article.md"
            out = root / "out.html"
            article.write_text("# 标题\n\n正文第一段。\n", encoding="utf-8")
            old_argv = sys.argv
            sys.argv = [
                "postprocess_wechat_article.py",
                str(article),
                str(out),
                "--no-images",
                "--publish-manifest",
            ]
            try:
                with self.assertRaises(SystemExit) as raised:
                    postprocess.main()
            finally:
                sys.argv = old_argv

        self.assertIn("--cover-image", str(raised.exception))

    def test_postprocess_passes_cover_image_to_no_image_package(self) -> None:
        commands: list[list[str]] = []

        def fake_run(command: list[str]) -> None:
            commands.append(command)

        original_run = postprocess.run
        try:
            postprocess.run = fake_run
            with tempfile.TemporaryDirectory() as tmp_dir:
                root = Path(tmp_dir)
                article = root / "article.md"
                out = root / "out.html"
                cover = root / "cover.png"
                article.write_text("# 标题\n\n正文第一段。\n", encoding="utf-8")
                cover.write_bytes(b"ok")
                old_argv = sys.argv
                sys.argv = [
                    "postprocess_wechat_article.py",
                    str(article),
                    str(out),
                    "--no-images",
                    "--publish-manifest",
                    "--cover-image",
                    str(cover),
                ]
                try:
                    postprocess.main()
                finally:
                    sys.argv = old_argv
        finally:
            postprocess.run = original_run

        command_text = "\n".join(" ".join(command) for command in commands)
        self.assertIn("--cover-image", command_text)
        self.assertIn(str(cover.resolve()), command_text)
        self.assertIn("--publish-manifest", command_text)

    def test_postprocess_passes_publisher_and_signature_options_to_packager(self) -> None:
        commands: list[list[str]] = []

        def fake_run(command: list[str]) -> None:
            commands.append(command)

        original_run = postprocess.run
        try:
            postprocess.run = fake_run
            with tempfile.TemporaryDirectory() as tmp_dir:
                root = Path(tmp_dir)
                article = root / "article.md"
                out = root / "out.html"
                cover = root / "cover.png"
                env_file = root / ".env"
                manifest = root / "custom.publish-manifest.json"
                article.write_text("# 标题\n\n正文第一段。\n", encoding="utf-8")
                cover.write_bytes(b"ok")
                env_file.write_text("", encoding="utf-8")
                old_argv = sys.argv
                sys.argv = [
                    "postprocess_wechat_article.py",
                    str(article),
                    str(out),
                    "--no-images",
                    "--cover-image",
                    str(cover),
                    "--publish-manifest-out",
                    str(manifest),
                    "--publisher-env-file",
                    str(env_file),
                    "--publisher-account",
                    "default",
                    "--author",
                    "接口作者",
                    "--signature-author",
                    "署名作者",
                    "--original-issue",
                    "8",
                ]
                try:
                    postprocess.main()
                finally:
                    sys.argv = old_argv
        finally:
            postprocess.run = original_run

        package_command = next(
            command for command in commands if "package_wechat_article_bundle.py" in " ".join(command)
        )
        command_text = " ".join(package_command)
        self.assertIn("--publish-manifest", package_command)
        self.assertIn(f"--publish-manifest-out {manifest.resolve()}", command_text)
        self.assertIn(f"--publisher-env-file {env_file.resolve()}", command_text)
        self.assertIn("--publisher-account default", command_text)
        self.assertIn("--author 接口作者", command_text)
        self.assertIn("--signature-author 署名作者", command_text)
        self.assertIn("--original-issue 8", command_text)

    def test_postprocess_passes_same_session_revision_to_packager(self) -> None:
        commands: list[list[str]] = []

        def fake_run(command: list[str]) -> None:
            commands.append(command)

        original_run = postprocess.run
        try:
            postprocess.run = fake_run
            with tempfile.TemporaryDirectory() as tmp_dir:
                root = Path(tmp_dir)
                article = root / "article.md"
                out = root / "out.html"
                cover = root / "cover.png"
                article.write_text("# 标题\n\n正文第一段。\n", encoding="utf-8")
                cover.write_bytes(b"ok")
                old_argv = sys.argv
                sys.argv = [
                    "postprocess_wechat_article.py",
                    str(article),
                    str(out),
                    "--no-images",
                    "--cover-image",
                    str(cover),
                    "--publish-manifest",
                    "--same-session-revision",
                ]
                try:
                    postprocess.main()
                finally:
                    sys.argv = old_argv
        finally:
            postprocess.run = original_run

        package_command = next(
            command for command in commands if "package_wechat_article_bundle.py" in " ".join(command)
        )
        self.assertIn("--same-session-revision", package_command)

    def test_filter_jobs_for_missing_images_keeps_only_missing_slots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            images_dir = Path(tmp_dir)
            (images_dir / "cover.png").write_bytes(b"ok")
            payload = {
                "slots": [
                    {"name": "cover", "output": "cover.png"},
                    {"name": "body-1", "output": "body-1.png"},
                    {"name": "closing", "output": "closing.png"},
                ],
                "generation_queue": [
                    {"slot": "cover", "output": "cover.png", "generation_prompt": "cover"},
                    {"slot": "body-1", "output": "body-1.png", "generation_prompt": "body"},
                    {"slot": "closing", "output": "closing.png", "generation_prompt": "closing"},
                ],
            }

            filtered = postprocess.filter_jobs_for_missing_images(payload, images_dir)

        self.assertEqual([slot["name"] for slot in filtered["slots"]], ["body-1", "closing"])
        self.assertEqual([item["slot"] for item in filtered["generation_queue"]], ["body-1", "closing"])
        self.assertNotIn("jobs", filtered)
        self.assertNotIn("image_slots", filtered)

    def test_missing_image_filter_requires_the_exact_planned_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            images_dir = Path(tmp_dir)
            (images_dir / "diagram.png").write_bytes(b"wrong extension")
            payload = {
                "kind": "wechat-image-jobs",
                "schema_version": 2,
                "article": {},
                "rules": {},
                "review_defaults": {},
                "slots": [{"name": "body-1", "output": "diagram.webp"}],
                "generation_queue": [
                    {
                        "slot": "body-1",
                        "output": "diagram.webp",
                        "generation_prompt": "diagram",
                    }
                ],
            }

            filtered = postprocess.filter_jobs_for_missing_images(payload, images_dir)

        self.assertEqual([slot["name"] for slot in filtered["slots"]], ["body-1"])


if __name__ == "__main__":
    unittest.main()
