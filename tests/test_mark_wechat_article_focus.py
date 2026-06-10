#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "wechat-article-pipeline" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import mark_wechat_article_focus as focus_marker  # noqa: E402


class WeChatArticleFocusTest(unittest.TestCase):
    def test_focus_marking_resumes_after_complete_fenced_code_block(self) -> None:
        paragraphs = "\n\n".join(
            [
                f"第{i}段，真正重要的是这里应该独立出现一个重点句，而不是全部合并在最后。"
                for i in range(1, 4)
            ]
        )
        markdown = f"""# 标题

```text
AGENTS.md

PROJECTS.md
```

{paragraphs}
"""

        marked = focus_marker.mark_article(markdown, target_chars=30, max_bold=0)

        for index in range(1, 4):
            self.assertIn(f"**第{index}段，真正重要的是这里应该独立出现一个重点句，而不是全部合并在最后。**", marked)


if __name__ == "__main__":
    unittest.main()
