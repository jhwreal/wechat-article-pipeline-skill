#!/usr/bin/env python3
from __future__ import annotations

import base64
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "wechat-article-pipeline" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import make_wechat_publish_manifest as manifest_builder  # noqa: E402
import publish_wechat_api as publisher  # noqa: E402


PNG_1X1 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR42mNk+M/wHwAF/gL+IpcQ3wAAAABJRU5ErkJggg=="


class WeChatDraftHtmlTest(unittest.TestCase):
    def test_source_state_json_requires_an_object(self) -> None:
        state = manifest_builder.parse_source_state_json(
            '{"core_revision":2,"manifest_revision":2,"asset_state":"ready"}'
        )
        self.assertEqual(state["core_revision"], 2)
        with self.assertRaisesRegex(SystemExit, "JSON object"):
            manifest_builder.parse_source_state_json("[]")

    def test_draft_renderer_drops_executable_markdown_urls(self) -> None:
        rendered = manifest_builder.inline_format(
            "[危险链接](java\tscript:evil) 与 ![危险图片](javascript:evil)"
        )
        safe = manifest_builder.inline_format("[官网](https://example.com)")

        self.assertNotIn("href=", rendered)
        self.assertNotIn("src=", rendered)
        self.assertIn("危险链接", rendered)
        self.assertIn('href="https://example.com"', safe)

    def test_draft_body_omits_leading_title_before_cover_and_signature(self) -> None:
        markdown = """# 标题

![题图](data:image/png;base64,abc)

正文第一段。
"""
        title = manifest_builder.extract_title(markdown, "fallback")
        body_markdown = manifest_builder.markdown_for_draft_body(markdown, title)
        html = manifest_builder.inject_signature_html(
            manifest_builder.markdown_to_wechat_html(body_markdown),
            "树懒的第209篇原创",
        )

        self.assertNotIn(">标题</p>", html)
        self.assertLess(html.index("<img "), html.index("树懒的第209篇原创"))
        self.assertLess(html.index("树懒的第209篇原创"), html.index("正文第一段"))

    def test_draft_body_omits_title_after_leading_cover(self) -> None:
        markdown = """![题图](data:image/png;base64,abc)

# 标题

正文第一段。
"""
        title = manifest_builder.extract_title(markdown, "fallback")
        body_markdown = manifest_builder.markdown_for_draft_body(markdown, title)
        html = manifest_builder.markdown_to_wechat_html(body_markdown)

        self.assertNotIn(">标题</p>", html)
        self.assertLess(html.index("<img "), html.index("正文第一段"))

    def test_manifest_html_is_draft_safe_and_keeps_fenced_code_together(self) -> None:
        markdown = """# 标题

![题图](data:image/png;base64,abc)

正文第一段。

```text
AGENTS.md

PROJECTS.md
```

> 引用一
> 引用二

- 第一项
- 第二项
"""
        html = manifest_builder.inject_signature_html(
            manifest_builder.markdown_to_wechat_html(markdown),
            "树懒的第209篇原创",
        )

        lowered = html.lower()
        for tag in ("section", "div", "blockquote", "pre", "ul", "ol"):
            self.assertNotIn(f"<{tag}", lowered)
            self.assertNotIn(f"</{tag}", lowered)
        self.assertNotIn("```", html)
        self.assertNotRegex(html, r"<p[^>]*>\s*</p>")
        self.assertIn("树懒的第209篇原创", html)
        self.assertIn("AGENTS.md<br>&nbsp;<br>PROJECTS.md", html)
        self.assertIn("• 第一项<br>• 第二项", html)

    def test_h2_badge_background_stays_on_text_width(self) -> None:
        html = manifest_builder.markdown_to_wechat_html("## 那封回信，比授权本身更暖")

        opening_paragraph = html.split(">", 1)[0]
        self.assertIn("text-align:center", opening_paragraph)
        self.assertNotIn("background:#17b394", opening_paragraph)
        self.assertIn(
            '<span style="display:inline-block;max-width:100%;box-sizing:border-box;',
            html,
        )
        self.assertIn("background:#17b394", html)
        self.assertIn(">那封回信，比授权本身更暖</span>", html)
        self.assertNotIn("width:fit-content", html)

    def test_markdown_tables_remain_real_wechat_tables(self) -> None:
        markdown = """| 模型 | 普通输入 | 输出 |
|---|---:|---:|
| `Qwen3.8-Max` | 12 元 | 36 元 |
| `DeepSeek V4 Pro` | 3 元 | 6 元 |
"""
        html = manifest_builder.markdown_to_wechat_html(markdown)

        self.assertIn('<table style="', html)
        self.assertIn("<thead><tr>", html)
        self.assertIn("<tbody><tr>", html)
        self.assertIn("text-align:right", html)
        self.assertIn(">Qwen3.8-Max</code>", html)
        self.assertNotIn("|---", html)
        publisher.validate_manifest(
            {"title": "标题", "digest": "摘要", "cover": {"src": PNG_1X1}},
            html,
        )

    def test_publisher_rejects_unstable_draft_tags(self) -> None:
        manifest = {
            "title": "标题",
            "digest": "摘要",
            "cover": {"src": "data:image/png;base64,abc"},
        }
        with self.assertRaises(SystemExit):
            publisher.validate_manifest(
                manifest,
                '<section><p><img src="data:image/png;base64,abc"></p></section>',
            )

    def test_publisher_allows_article_without_body_images_when_cover_exists(self) -> None:
        validation = publisher.validate_manifest(
            {
                "title": "标题",
                "digest": "摘要",
                "cover": {"src": PNG_1X1},
            },
            "<p>正文第一段。</p>",
        )

        self.assertEqual(validation["body_data_image_count"], 0)
        self.assertTrue(validation["cover_is_data_uri"])

    def test_publisher_rejects_stale_source_state(self) -> None:
        manifest = {"title": "标题", "digest": "摘要", "cover": {"src": PNG_1X1},
                    "source_state": {"core_revision": 3, "manifest_revision": 2,
                                      "asset_state": "ready", "stale_visuals": [], "missing_visuals": []}}
        with self.assertRaises(SystemExit):
            publisher.validate_manifest(manifest, "<p>正文</p>")

    def test_publisher_accepts_legacy_manifest_without_source_state(self) -> None:
        result = publisher.validate_manifest({"title": "标题", "digest": "摘要", "cover": {"src": PNG_1X1}}, "<p>正文</p>")
        self.assertTrue(result["cover_is_data_uri"])

    def test_publish_manifest_can_use_cover_visual_outside_article_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            cover = root / "cover.png"
            cover.write_bytes(base64.b64decode(PNG_1X1.split(",", 1)[1]))

            selected, candidates = manifest_builder.select_cover_candidate(
                "# 标题\n\n正文第一段。\n",
                {"cover": {"path": str(cover)}},
                root,
            )

        self.assertEqual(selected["name"], "cover")
        self.assertEqual(selected["alt"], "题图")
        self.assertTrue(selected["src"].startswith("data:image/png;base64,"))
        self.assertEqual(candidates[0], selected)

    def test_publish_manifest_rejects_external_body_image_sources(self) -> None:
        with self.assertRaisesRegex(SystemExit, "must resolve to embedded data:image"):
            manifest_builder.validate_publish_image_sources(
                "# 标题\n\n![外链图](https://example.com/image.png)\n",
                {"src": PNG_1X1},
            )

    def test_inline_code_is_not_reparsed_as_markdown_emphasis(self) -> None:
        html = manifest_builder.markdown_to_wechat_html("这里有 `**literal**` 和 `a*b`。")

        self.assertNotIn("<strong", html)
        self.assertNotIn("<em>", html)
        self.assertIn("**literal**", html)
        self.assertIn("a*b", html)

    def test_inline_code_placeholder_text_is_preserved(self) -> None:
        html = manifest_builder.markdown_to_wechat_html("保留 @@INLINE_CODE_0@@，同时 `code`。")

        self.assertIn("@@INLINE_CODE_0@@", html)
        self.assertEqual(html.count("<code "), 1)
        self.assertIn(">code</code>", html)

    def test_strip_markdown_preserves_leading_years_while_removing_list_markers(self) -> None:
        self.assertEqual(
            manifest_builder.strip_markdown("2026年，先看这个判断。"),
            "2026年，先看这个判断。",
        )
        self.assertEqual(manifest_builder.strip_markdown("1. 第一项"), "第一项")
        self.assertEqual(manifest_builder.strip_markdown("- 第一项"), "第一项")


if __name__ == "__main__":
    unittest.main()
