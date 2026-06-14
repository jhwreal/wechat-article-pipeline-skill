#!/usr/bin/env python3
from __future__ import annotations

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
        self.assertIn("--no-publish-manifest", command_text)
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
        self.assertNotIn("--no-publish-manifest", command_text)

    def test_filter_jobs_for_missing_images_keeps_only_missing_slots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            images_dir = Path(tmp_dir)
            (images_dir / "cover.png").write_bytes(b"ok")
            payload = {
                "image_slots": [{"name": "cover"}, {"name": "body-1"}, {"name": "closing"}],
                "jobs": [
                    {"name": "cover", "output": "cover.png"},
                    {"name": "body-1", "output": "body-1.png"},
                    {"name": "closing", "output": "closing.png"},
                ],
                "generation_queue": [
                    {"slot": "cover", "id": "01A"},
                    {"slot": "body-1", "id": "02A"},
                    {"slot": "closing", "id": "03A"},
                ],
                "image_plan": {
                    "image_slots": [{"name": "cover"}, {"name": "body-1"}, {"name": "closing"}],
                },
            }

            filtered = postprocess.filter_jobs_for_missing_images(payload, images_dir)

        self.assertEqual([job["name"] for job in filtered["jobs"]], ["body-1", "closing"])
        self.assertEqual([slot["name"] for slot in filtered["image_slots"]], ["body-1", "closing"])
        self.assertEqual(
            [slot["name"] for slot in filtered["image_plan"]["image_slots"]],
            ["body-1", "closing"],
        )
        self.assertEqual([item["slot"] for item in filtered["generation_queue"]], ["body-1", "closing"])


if __name__ == "__main__":
    unittest.main()
