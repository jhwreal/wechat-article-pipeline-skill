#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "wechat-article-pipeline" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import make_wechat_publish_manifest as manifest_builder  # noqa: E402
import publish_wechat_api as publisher  # noqa: E402


class WeChatDraftHtmlTest(unittest.TestCase):
    def test_manifest_html_is_paragraph_only_and_keeps_fenced_code_together(self) -> None:
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
