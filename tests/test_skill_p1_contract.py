#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
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
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR42mNk+M/wHwAF/gL+IpcQ3wAAAABJRU5ErkJggg=="
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

        self.assertEqual(payload["kind"], "wechat-image-jobs")
        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual(payload["slots"], [])
        self.assertEqual(payload["generation_queue"], [])
        self.assertEqual(payload["article"]["visual_mode"], "no_image")

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
        self.assertEqual(payload["article"]["planning_mode"], "fast")
        self.assertEqual(payload["article"]["skipped_visuals"], ["body-2"])

    def test_image_jobs_reject_invalid_rhythm_and_noncanonical_placeholders(self) -> None:
        markdown = (
            "# 标题\n\n"
            "![题图]({{visual:cover}})\n\n"
            "正文。\n\n![配图]({{visual:body-zero}})\n\n"
            "![尾图]({{visual:closing}})\n"
        )
        with self.assertRaisesRegex(SystemExit, "Unsupported visual placeholders"):
            image_jobs.build_jobs(
                article_path=Path("article.md"),
                article_slug="article",
                markdown=markdown,
                target_body_chars=200,
                min_body_chars=120,
            )

        with self.assertRaisesRegex(SystemExit, "target-body-chars"):
            image_jobs.build_jobs(
                article_path=Path("article.md"),
                article_slug="article",
                markdown=markdown,
                target_body_chars=0,
                min_body_chars=120,
                mode="no-image",
            )

    def test_image_jobs_missing_only_filters_generation_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            images_dir = Path(tmp_dir)
            (images_dir / "cover.png").write_bytes(b"ok")
            payload = {
                "slots": [{"name": "cover", "output":"cover.png"}, {"name": "body-1", "output":"body-1.png"}],
                "generation_queue": [
                    {"slot": "cover", "output": "cover.png", "generation_prompt": "cover"},
                    {"slot": "body-1", "output": "body-1.png", "generation_prompt": "body"},
                ],
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
        self.assertNotIn("variants", payload["slots"][0])
        self.assertNotIn("candidate_output", payload["generation_queue"][0])
        self.assertNotIn("review_contract", payload["generation_queue"][0])
        self.assertNotIn("generation_prompt", payload["slots"][0])
        self.assertEqual(set(payload["generation_queue"][0]), {"slot", "output", "generation_prompt"})

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

        for job in payload["slots"]:
            self.assertNotIn("generation_prompt", job)
            self.assertNotIn("review_contract", job)
            self.assertIn("must_include", job)
            self.assertIn("quality_gate", job)

        prompts = {item["slot"]: item["generation_prompt"] for item in payload["generation_queue"]}
        for prompt in prompts.values():
            self.assertIn("视觉类型", prompt)
            self.assertIn("文字预算", prompt)
            self.assertIn("质感要求", prompt)
            self.assertIn("3:2", prompt)
            self.assertIn("横版", prompt)
            self.assertIn("1536×1024", prompt)
            self.assertNotIn("generic wallpaper", prompt)
            self.assertNotIn("官网链接", prompt)

        cover = next(job for job in payload["slots"] if job["name"] == "cover")
        body = next(job for job in payload["slots"] if job["name"] == "body-1")
        closing = next(job for job in payload["slots"] if job["name"] == "closing")
        prompts = {item["slot"]: item["generation_prompt"] for item in payload["generation_queue"]}
        self.assertIn("钩子", prompts["cover"])
        self.assertIn("读者", prompts["body-1"])
        self.assertNotIn("正文图优先", prompts["cover"])
        self.assertRegex(prompts["closing"], r"余韵|象征")
        self.assertNotIn("正文图优先", prompts["closing"])

        for item in payload["generation_queue"]:
            self.assertIn("generation_prompt", item)
            self.assertNotIn("review_contract", item)
            self.assertEqual(set(item), {"slot", "output", "generation_prompt"})

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

        for job in payload["slots"]:
            self.assertNotIn("variants", job)
            self.assertNotIn("generation_prompt", job)
        for item in payload["generation_queue"]:
            self.assertIn("generation_prompt", item)

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
        self.assertIn("strict 3:2 landscape", image_production)
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

        expected_avoids = payload["review_defaults"]["must_avoid"]
        self.assertIn("must_avoid", payload["review_defaults"])
        self.assertIn("quality_floor", payload["review_defaults"])
        rules = json.loads((SKILL_DIR / "references" / "image-rules.json").read_text(encoding="utf-8"))
        rules_bytes = json.dumps(
            rules, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        self.assertEqual(payload["rules"]["sha256"], hashlib.sha256(rules_bytes).hexdigest())
        self.assertEqual(expected_avoids, rules["avoid_rules"])
        self.assertEqual(payload["review_defaults"]["quality_floor"], rules["quality_floor_rules"])
        for key in (
            "visual_mode",
            "visual_intent",
            "summary",
            "essence",
            "global_visual_style",
            "source",
        ):
            self.assertTrue(payload["article"].get(key), key)

        for job in payload["slots"]:
            self.assertNotIn("generation_prompt", job)
            self.assertIn("visual_type", job)

        for item in payload["generation_queue"]:
            self.assertNotIn("review_contract", item)

    def test_skill_routes_image_generation_rules_to_reference(self) -> None:
        skill_md = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("image-production.md", skill_md)
        self.assertIn("single-pass", skill_md)
        self.assertIn("currently available worker slots", skill_md)
        self.assertNotIn("two candidates", skill_md)

    def test_skill_draft_creation_advances_original_issue(self) -> None:
        skill_md = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("automatically advances the issue counter", skill_md)
        self.assertIn("do not rely on callers remembering an extra flag", skill_md)

    def test_skill_keeps_platform_views_lazy(self) -> None:
        skill_md = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("Mount only the active platform preview", skill_md)
        self.assertIn("sole Markdown source", skill_md)
        self.assertIn("Cache semantic HTML", skill_md)
        self.assertIn("only while copying", skill_md)

    def test_toutiao_contract_enforces_workbench_first_and_publish_gate(self) -> None:
        skill_md = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        toutiao = (SKILL_DIR / "references" / "publishing-toutiao.md").read_text(encoding="utf-8")

        self.assertIn("before the first browser write", skill_md)
        self.assertIn("选择头条格式 → 点击 `复制为头条格式`", toutiao)
        self.assertIn("不得改走头条的单图上传按钮", toutiao)
        self.assertIn("成功回执中的正文图片 HTTPS 托管地址会按原顺序自动回填工作台", toutiao)
        self.assertIn("点击一次 `复制为头条格式`", toutiao)
        self.assertIn("执行一次 `super+v`", toutiao)
        self.assertIn("不得用浏览器虚拟剪贴板替代", toutiao)
        self.assertIn("`super+a` / `super+v`", toutiao)
        self.assertIn("必须保留全部图片、单级标题、列表、加粗和原始顺序", toutiao)
        self.assertIn("不自行改换正文导入方式", toutiao)
        self.assertIn("提交前硬门槛", toutiao)
        self.assertIn("外部链接数量必须为 0", toutiao)
        self.assertIn("按头条私有图片 URL 去重后的图片数等于预期图片数", toutiao)
        self.assertIn("头条图文默认选择 `投放广告赚收益`", toutiao)
        self.assertIn("不要把“去除微信正文里的广告卡片”误解为关闭头条广告收益", toutiao)
        self.assertIn("两个广告选项都未选中时，不得保存草稿或提交", toutiao)
        self.assertIn("toutiao_ads_enabled: true|false", toutiao)
        self.assertIn("将于 MM-DD HH:mm 发布", toutiao)

    def test_xiaohongshu_contract_preserves_two_heading_levels_and_avoids_private_api(self) -> None:
        skill_md = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        xiaohongshu = (SKILL_DIR / "references" / "publishing-xiaohongshu.md").read_text(encoding="utf-8")

        self.assertIn("publishing-xiaohongshu.md", skill_md)
        self.assertIn("选择小红书格式 → 点击 `复制为小红书格式`", xiaohongshu)
        self.assertIn("Markdown `##` → 小红书 `h1`", xiaohongshu)
        self.assertIn("Markdown `###`", xiaohongshu)
        self.assertIn("macOS 系统剪贴板", xiaohongshu)
        self.assertIn("不得用浏览器虚拟剪贴板替代", xiaohongshu)
        self.assertIn("真实工作台整篇粘贴", xiaohongshu)
        self.assertIn("Base64 内嵌图片", xiaohongshu)
        self.assertIn("data:image", xiaohongshu)
        self.assertIn("正常同步的 `heading_repairs` 和 `image_repairs` 都必须为 `0`", xiaohongshu)
        self.assertIn("只读标题 DOM 审计", xiaohongshu)
        self.assertIn("外部链接数量为 0", xiaohongshu)
        self.assertIn("不调用、复制或固化 `creator.xiaohongshu.com` 的私有接口", xiaohongshu)
        self.assertIn("official_api_available", xiaohongshu)

    def test_three_platform_sync_uses_resumable_aggregate_state(self) -> None:
        skill_md = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        reference = (SKILL_DIR / "references" / "publishing-three-platform.md").read_text(
            encoding="utf-8"
        )
        state_script = SKILL_DIR / "scripts" / "platform_delivery_state.py"

        self.assertIn("publishing-three-platform.md", skill_md)
        self.assertTrue(state_script.is_file())
        self.assertIn("微信 → 头条 → 小红书", reference)
        self.assertIn("three-platform-result.json", reference)
        self.assertIn("submission_maybe_sent=true", reference)
        self.assertIn("verified` 平台不得重复创建草稿", reference)

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

    def test_explicit_packaging_increment_uses_compare_and_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            env = root / ".env"
            article = root / "article.md"
            out = root / "article.html"
            env.write_text(
                "WECHAT_SIGNATURE_AUTHOR=作者\nWECHAT_ORIGINAL_ISSUE=9\n",
                encoding="utf-8",
            )
            article.write_text("# 标题\n\n正文第一段。\n", encoding="utf-8")
            calls = []
            original_compare_and_set = packager.account_config.compare_and_set_env_value

            def record_compare_and_set(path, key, expected, value):
                calls.append((path, key, expected, value))
                return "updated"

            packager.account_config.compare_and_set_env_value = record_compare_and_set
            old_argv = sys.argv
            sys.argv = [
                "package_wechat_article_bundle.py",
                str(article),
                str(out),
                "--no-images",
                "--publisher-env-file",
                str(env),
                "--increment-original-issue",
            ]
            try:
                packager.main()
            finally:
                sys.argv = old_argv
                packager.account_config.compare_and_set_env_value = original_compare_and_set

        self.assertEqual(calls, [(env, "WECHAT_ORIGINAL_ISSUE", "9", "10")])

    def test_skill_marks_install_assets_as_not_runtime_context(self) -> None:
        skill_md = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn(".env.example", skill_md)
        self.assertIn("only for requested API setup", skill_md)
        self.assertNotIn("README.md", skill_md)
        self.assertNotIn("examples/", skill_md)


if __name__ == "__main__":
    unittest.main()
