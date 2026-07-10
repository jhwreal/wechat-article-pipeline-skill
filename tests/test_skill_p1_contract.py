#!/usr/bin/env python3
from __future__ import annotations

import base64
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "wechat-article-pipeline"
SCRIPTS = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS))

import make_wechat_article_image_jobs as image_jobs  # noqa: E402
import package_wechat_article_bundle as packager  # noqa: E402
import publish_wechat_api as publisher  # noqa: E402


PNG_1X1_DATA_URI = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lpI1GQAAAABJRU5ErkJggg=="
)
PNG_1X1_BYTES = base64.b64decode(PNG_1X1_DATA_URI.split(",", 1)[1])


class SkillP1ContractTest(unittest.TestCase):
    def test_publish_script_defaults_to_dry_run_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            manifest = root / "article.publish-manifest.json"
            result = root / "result.json"
            env = root / "empty.env"
            env.write_text("", encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {
                        "title": "标题",
                        "author": "作者",
                        "digest": "摘要",
                        "content_html": "<p>正文第一段。</p>",
                        "cover": {"src": PNG_1X1_DATA_URI},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            old_argv = sys.argv
            sys.argv = [
                "publish_wechat_api.py",
                str(manifest),
                "--env-file",
                str(env),
                "--out",
                str(result),
            ]
            try:
                publisher.main()
            finally:
                sys.argv = old_argv

            payload = json.loads(result.read_text(encoding="utf-8"))

        self.assertTrue(payload["dry_run"])
        self.assertNotIn("draft_media_id", payload)
        self.assertEqual(payload["draft_payload_summary"]["thumb_media_id"], "DRY_RUN_THUMB_MEDIA_ID")

    def test_publish_dry_run_does_not_require_account_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            manifest = root / "article.publish-manifest.json"
            result = root / "result.json"
            env = root / ".env"
            env.write_text(
                "\n".join(
                    [
                        "WECHAT_ACCOUNT_A_NAME=账号A",
                        "WECHAT_ACCOUNT_A_APPID=a",
                        "WECHAT_ACCOUNT_A_APPSECRET=a-secret",
                        "WECHAT_ACCOUNT_B_NAME=账号B",
                        "WECHAT_ACCOUNT_B_APPID=b",
                        "WECHAT_ACCOUNT_B_APPSECRET=b-secret",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            manifest.write_text(
                json.dumps(
                    {
                        "title": "标题",
                        "author": "作者",
                        "digest": "摘要",
                        "content_html": "<p>正文第一段。</p>",
                        "cover": {"src": PNG_1X1_DATA_URI},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            old_argv = sys.argv
            sys.argv = [
                "publish_wechat_api.py",
                str(manifest),
                "--env-file",
                str(env),
                "--out",
                str(result),
            ]
            try:
                publisher.main()
            finally:
                sys.argv = old_argv

            payload = json.loads(result.read_text(encoding="utf-8"))

        self.assertTrue(payload["dry_run"])

    def test_send_preview_requires_explicit_create_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            manifest = root / "article.publish-manifest.json"
            env = root / "empty.env"
            env.write_text("", encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {
                        "title": "标题",
                        "author": "作者",
                        "digest": "摘要",
                        "content_html": "<p>正文第一段。</p>",
                        "cover": {"src": PNG_1X1_DATA_URI},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            old_argv = sys.argv
            sys.argv = [
                "publish_wechat_api.py",
                str(manifest),
                "--env-file",
                str(env),
                "--send-preview",
            ]
            try:
                with self.assertRaises(SystemExit) as raised:
                    publisher.main()
            finally:
                sys.argv = old_argv

        self.assertIn("--create-draft", str(raised.exception))

    def test_verify_package_script_accepts_complete_package(self) -> None:
        verifier = importlib.import_module("verify_wechat_article_package")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            html = root / "article.html"
            job = root / "article.job.json"
            manifest = root / "article.publish-manifest.json"
            html.write_text(f"<html><body><img src=\"{PNG_1X1_DATA_URI}\"></body></html>", encoding="utf-8")
            job.write_text(
                json.dumps(
                    {
                        "article_markdown": "# 标题\n\n![题图]({{visual:cover}})\n\n正文。",
                        "visuals": {"cover": {"data_uri": PNG_1X1_DATA_URI}},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manifest.write_text(
                json.dumps(
                    {
                        "title": "标题",
                        "digest": "摘要",
                        "content_html": f"<p><img src=\"{PNG_1X1_DATA_URI}\"></p><p>正文。</p>",
                        "cover": {"src": PNG_1X1_DATA_URI},
                        "workbench_html": str(html),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            report = verifier.verify_package(html, job_path=job, manifest_path=manifest)

        self.assertEqual(report["status"], "ok")
        self.assertFalse(report["failures"])

    def test_image_jobs_support_no_image_mode_without_placeholders(self) -> None:
        payload = image_jobs.build_jobs(
            article_path=Path("article.md"),
            article_slug="article",
            markdown="# 标题\n\n正文第一段。",
            target_body_chars=200,
            min_body_chars=120,
            mode="no-image",
        )

        self.assertEqual(payload["slots"], [])
        self.assertEqual(payload["image_slots"], [])
        self.assertEqual(payload["visual_mode"], "no_image")

    def test_image_jobs_fast_mode_caps_body_images(self) -> None:
        markdown = (
            "# 标题\n\n"
            "![题图]({{visual:cover}})\n\n"
            "第一段。\n\n![配图1]({{visual:body-1}})\n\n"
            "第二段。\n\n![配图2]({{visual:body-2}})\n\n"
            "第三段。\n\n![尾图]({{visual:closing}})\n"
        )

        payload = image_jobs.build_jobs(
            article_path=Path("article.md"),
            article_slug="article",
            markdown=markdown,
            target_body_chars=200,
            min_body_chars=120,
            mode="fast",
            max_body_images=1,
        )

        self.assertEqual([job["name"] for job in payload["slots"]], ["cover", "body-1", "closing"])

    def test_image_jobs_missing_only_filters_generation_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            images_dir = Path(tmp_dir)
            (images_dir / "cover.png").write_bytes(b"ok")
            payload = {
                "jobs": [{"name": "cover"}, {"name": "body-1"}],
                "image_slots": [{"name": "cover"}, {"name": "body-1"}],
                "generation_queue": [
                    {"slot": "cover", "id": "01"},
                    {"slot": "body-1", "id": "02"},
                ],
                "image_plan": {"image_slots": [{"name": "cover"}, {"name": "body-1"}]},
            }

            filtered = image_jobs.filter_missing_jobs(payload, images_dir)

        self.assertEqual([item["slot"] for item in filtered["generation_queue"]], ["body-1"])

    def test_image_jobs_emit_single_direct_generation_task_per_slot(self) -> None:
        markdown = (
            "# 标题\n\n"
            "![题图]({{visual:cover}})\n\n"
            "第一段讲一个新变化。\n\n![配图1]({{visual:body-1}})\n\n"
            "第二段讲一个选择。\n\n![尾图]({{visual:closing}})\n"
        )

        payload = image_jobs.build_jobs(
            article_path=Path("article.md"),
            article_slug="article",
            markdown=markdown,
            target_body_chars=200,
            min_body_chars=120,
        )

        queue = payload["generation_queue"]
        self.assertEqual(len(queue), 3)
        self.assertEqual([item["slot"] for item in queue], ["cover", "body-1", "closing"])
        self.assertEqual([item["output"] for item in queue], ["cover.png", "body-1.png", "closing.png"])
        self.assertEqual(payload["generation_queue"][0]["output"], "cover.png")
        self.assertNotIn("variants", payload["jobs"][0])
        self.assertNotIn("candidate_output", payload["generation_queue"][0])
        self.assertNotIn("review_contract", payload["generation_queue"][0])
        self.assertIn("material_name", payload["jobs"][0]["generation_task"])
        self.assertIn("01", payload["image_plan_markdown"])
        self.assertNotIn("01A", payload["image_plan_markdown"])
        self.assertNotIn("01B", payload["image_plan_markdown"])

    def test_image_jobs_split_short_generation_prompt_from_review_contract(self) -> None:
        markdown = (
            "# 三步写出让读者收藏的公众号文章\n\n"
            "![题图]({{visual:cover}})\n\n"
            "开头要先给读者一个愿意点开的钩子。\n\n"
            "![配图1]({{visual:body-1}})\n\n"
            "中间这一段讲方法，要让读者知道如何判断自己的文章有没有读者价值。\n\n"
            "![尾图]({{visual:closing}})\n"
        )

        payload = image_jobs.build_jobs(
            article_path=Path("article.md"),
            article_slug="article",
            markdown=markdown,
            target_body_chars=220,
            min_body_chars=120,
        )

        for job in payload["jobs"]:
            self.assertIn("generation_prompt", job)
            self.assertIn("review_contract", job)
            self.assertEqual(job["prompt"], job["generation_prompt"])
            self.assertIn("视觉类型", job["generation_prompt"])
            self.assertIn("文字预算", job["generation_prompt"])
            self.assertIn("质感要求", job["generation_prompt"])
            self.assertIn("高端中文杂志", job["generation_prompt"])
            self.assertIn("光线方向", job["generation_prompt"])
            self.assertIn("材质", job["generation_prompt"])
            self.assertIn("手机窄屏", job["generation_prompt"])
            self.assertIn("硬性限制", job["generation_prompt"])
            self.assertNotIn("generic wallpaper", job["generation_prompt"])
            self.assertNotIn("官网链接", job["generation_prompt"])
            self.assertIn("selection_criteria", job["review_contract"])
            self.assertIn("must_include", job["review_contract"])
            self.assertIn("quality_gate", job["review_contract"])
            self.assertIn("must_avoid", job["review_contract"])
            self.assertIn("visual_type", job["review_contract"])
            self.assertIn("text_budget", job["review_contract"])
            self.assertIn("quality_floor", job["review_contract"])

        cover = next(job for job in payload["jobs"] if job["name"] == "cover")
        body = next(job for job in payload["jobs"] if job["name"] == "body-1")
        closing = next(job for job in payload["jobs"] if job["name"] == "closing")
        self.assertIn("钩子", cover["generation_prompt"])
        self.assertIn("读者", body["generation_prompt"])
        self.assertNotIn("正文图优先", cover["generation_prompt"])
        self.assertRegex(closing["generation_prompt"], r"余韵|象征")
        self.assertNotIn("正文图优先", closing["generation_prompt"])

        for item in payload["generation_queue"]:
            self.assertIn("generation_prompt", item)
            self.assertNotIn("review_contract", item)
            self.assertEqual(item["prompt"], item["generation_prompt"])

    def test_image_jobs_do_not_emit_candidate_variants(self) -> None:
        markdown = (
            "# 普通人如何把复杂问题讲清楚\n\n"
            "![题图]({{visual:cover}})\n\n"
            "第一段先提出复杂问题为什么会吓退读者。\n\n"
            "![配图1]({{visual:body-1}})\n\n"
            "第二段给出一个可执行的拆解方法。\n\n"
            "![尾图]({{visual:closing}})\n"
        )

        payload = image_jobs.build_jobs(
            article_path=Path("article.md"),
            article_slug="article",
            markdown=markdown,
            target_body_chars=220,
            min_body_chars=120,
        )

        for job in payload["jobs"]:
            self.assertNotIn("variants", job)
            task = job["generation_task"]
            self.assertEqual(task["generation_prompt"], job["generation_prompt"])
            self.assertEqual(task["prompt"], task["generation_prompt"])
            self.assertEqual(task["output"], job["output"])
            self.assertNotIn("review_contract", task)
            self.assertIn("直接生成", task["direction"])

    def test_image_rules_are_single_source_and_include_prompt_guardrails(self) -> None:
        rules_path = SKILL_DIR / "references" / "image-rules.json"
        rules = json.loads(rules_path.read_text(encoding="utf-8"))

        self.assertGreaterEqual(len(rules["avoid_rules"]), 8)
        self.assertTrue(any("PPT" in rule for rule in rules["avoid_rules"]))
        self.assertTrue(any("小字墙" in rule for rule in rules["avoid_rules"]))
        self.assertTrue(any("总结卡" in rule for rule in rules["avoid_rules"]))
        self.assertFalse(rules["print_before_generation"])
        self.assertIn("generation_rules", rules)
        self.assertIn("influencing_rules", rules)
        self.assertIn("slot_objectives", rules)
        self.assertIn("text_budget_rules", rules)
        self.assertIn("visual_type_rules", rules)
        self.assertIn("quality_floor_rules", rules)
        self.assertIn("prompt_guardrails", rules)
        self.assertIn("prompt_hard_limits", rules)

        image_production = (SKILL_DIR / "references" / "image-production.md").read_text(encoding="utf-8")
        style_guide = (SKILL_DIR / "references" / "style-guide.md").read_text(encoding="utf-8")
        self.assertIn("image-rules.json", image_production)
        self.assertIn("image-rules.json", style_guide)
        self.assertNotIn("generic wallpaper", image_production)
        self.assertNotIn("dense PPT-style", style_guide)

    def test_image_jobs_use_central_rules_and_emit_conversation_summary(self) -> None:
        markdown = (
            "# 三步写出让读者收藏的公众号文章\n\n"
            "![题图]({{visual:cover}})\n\n"
            "开头要先给读者一个愿意点开的钩子。\n\n"
            "![配图1]({{visual:body-1}})\n\n"
            "中间这一段讲方法，要让读者知道如何判断自己的文章有没有读者价值。\n\n"
            "![尾图]({{visual:closing}})\n"
        )

        payload = image_jobs.build_jobs(
            article_path=Path("article.md"),
            article_slug="article",
            markdown=markdown,
            target_body_chars=220,
            min_body_chars=120,
        )

        expected_avoids = payload["image_rules"]["avoid_rules"]
        self.assertEqual(payload["image_rules"]["avoid_rules"], expected_avoids)
        self.assertIn("## 当前生图规则", payload["image_rules_markdown"])
        self.assertIn("## 当前避免规则", payload["image_rules_markdown"])
        self.assertIn("## 当前文字预算", payload["image_rules_markdown"])
        self.assertIn("## 当前视觉类型", payload["image_rules_markdown"])
        self.assertIn("## 当前质感要求", payload["image_rules_markdown"])
        self.assertIn("## 当前生成硬限制", payload["image_rules_markdown"])
        self.assertIn("## 影响生成图片的规则", payload["image_rules_markdown"])

        for job in payload["jobs"]:
            self.assertEqual(job["must_avoid"], expected_avoids)
            self.assertEqual(job["review_contract"]["must_avoid"], expected_avoids)
            self.assertIn("小字墙", job["generation_prompt"])
            self.assertIn("PPT", job["generation_prompt"])
            self.assertNotIn("generic wallpaper", job["generation_prompt"])
            self.assertTrue(any("generic wallpaper" in rule for rule in job["review_contract"]["must_avoid"]))
            self.assertIn("text_budget", job)
            self.assertIn("visual_type", job)

        for item in payload["generation_queue"]:
            self.assertNotIn("review_contract", item)

    def test_skill_routes_image_generation_rules_to_reference(self) -> None:
        skill_md = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("image-production.md", skill_md)
        self.assertIn("single-pass", skill_md)
        self.assertIn("4 image worker subagents", skill_md)
        self.assertNotIn("two candidates", skill_md)

    def test_skill_draft_creation_advances_original_issue(self) -> None:
        skill_md = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("--create-draft --increment-original-issue", skill_md)

    def test_packaging_does_not_increment_original_issue_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            env = root / ".env"
            article = root / "article.md"
            out = root / "article.html"
            env.write_text("WECHAT_SIGNATURE_AUTHOR=作者\nWECHAT_ORIGINAL_ISSUE=9\n", encoding="utf-8")
            article.write_text("# 标题\n\n正文第一段。\n", encoding="utf-8")
            old_argv = sys.argv
            sys.argv = [
                "package_wechat_article_bundle.py",
                str(article),
                str(out),
                "--no-images",
                "--no-publish-manifest",
                "--publisher-env-file",
                str(env),
            ]
            try:
                packager.main()
            finally:
                sys.argv = old_argv

            env_text = env.read_text(encoding="utf-8")

        self.assertIn("WECHAT_ORIGINAL_ISSUE=9", env_text)
        self.assertNotIn("WECHAT_ORIGINAL_ISSUE=10", env_text)

    def test_skill_marks_install_assets_as_not_runtime_context(self) -> None:
        skill_md = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("README.md", skill_md)
        self.assertIn("examples/", skill_md)
        self.assertIn("do not read", skill_md)


if __name__ == "__main__":
    unittest.main()
