from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "serve_wechat_workbench.py"
TEMPLATE = ROOT / "assets" / "templates" / "wechat-md-workbench.template.v3.html"


def load_server_module():
    if not SCRIPT.exists():
        raise AssertionError(f"missing local workbench server: {SCRIPT}")
    spec = importlib.util.spec_from_file_location("serve_wechat_workbench", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load serve_wechat_workbench.py")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


class WorkbenchTemplateTests(unittest.TestCase):
    def test_template_keeps_standalone_local_storage_and_adds_optional_server_save(self):
        source = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("localStorage.setItem", source)
        self.assertIn("/__wechat_workbench/save", source)
        self.assertIn("127.0.0.1", source)
        self.assertIn("localhost", source)
        self.assertIn("catch", source)


class WorkbenchDocumentTests(unittest.TestCase):
    def test_rendered_image_paths_are_restored_to_visual_placeholders(self):
        module = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            html_path = workspace / "files" / "demo.html"
            job_path = workspace / "files" / "demo.job.json"
            image_path = workspace / "image" / "demo" / "cover.png"
            html_path.parent.mkdir(parents=True)
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"png")
            job = {"visuals": {"cover": {"path": str(image_path)}}}
            rendered = "# 新标题\n\n![题图](../image/demo/cover.png)\n"

            restored = module.restore_visual_placeholders(rendered, job, html_path)

            self.assertEqual(restored, "# 新标题\n\n![题图]({{visual:cover}})\n")

    def test_save_updates_html_markdown_and_job_while_preserving_standalone_mode(self):
        module = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            files_dir = workspace / "files"
            image_dir = workspace / "image" / "demo"
            files_dir.mkdir(parents=True)
            image_dir.mkdir(parents=True)
            html_path = files_dir / "demo.html"
            markdown_path = files_dir / "demo.md"
            job_path = files_dir / "demo.job.json"
            image_path = image_dir / "cover.png"
            image_path.write_bytes(b"png")
            html_path.write_text(
                "<script>const DEFAULT_MARKDOWN = `旧稿`;\n"
                "const DEFAULT_WORKBENCH_STATE = {\"themeColor\":\"#17b394\",\"fontSize\":\"16\",\"fontFamily\":\"sans-serif\"};\n"
                "localStorage.setItem('x', 'y');</script>",
                encoding="utf-8",
            )
            markdown_path.write_text("旧稿\n", encoding="utf-8")
            job_path.write_text(
                json.dumps(
                    {
                        "article_markdown": "旧稿",
                        "visuals": {"cover": {"path": str(image_path)}},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            document = module.WorkbenchDocument(html_path=html_path, workspace=workspace)
            payload = {
                "markdown": "# 最终稿\n\n![题图](../image/demo/cover.png)\n",
                "themeColor": "#123456",
                "fontSize": "18",
                "fontFamily": "serif",
            }

            result = document.save(payload)

            saved_html = html_path.read_text(encoding="utf-8")
            saved_markdown = markdown_path.read_text(encoding="utf-8")
            saved_job = json.loads(job_path.read_text(encoding="utf-8"))
            self.assertTrue(result["saved"])
            self.assertIn("# 最终稿", saved_html)
            self.assertIn("localStorage.setItem", saved_html)
            self.assertIn('"themeColor":"#123456"', saved_html)
            self.assertEqual(saved_markdown, "# 最终稿\n\n![题图]({{visual:cover}})\n")
            self.assertEqual(saved_job["article_markdown"], saved_markdown)

    def test_paths_outside_workspace_are_rejected(self):
        module = load_server_module()
        with tempfile.TemporaryDirectory() as workspace_dir, tempfile.TemporaryDirectory() as outside_dir:
            workspace = Path(workspace_dir)
            outside_html = Path(outside_dir) / "outside.html"
            outside_html.write_text("x", encoding="utf-8")

            with self.assertRaises(ValueError):
                module.WorkbenchDocument(html_path=outside_html, workspace=workspace)

    def test_staged_transaction_replays_on_startup(self):
        module = load_server_module()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); html=root/'a.html'; html.write_text('old', encoding='utf-8')
            support=root/'support'; staged=support/'.txn/1/a.html'; staged.parent.mkdir(parents=True)
            staged.write_text('new', encoding='utf-8'); import hashlib, json
            (support/'a.transaction.json').write_text(json.dumps({'revision':1,'files':[{'target':str(html),'staged':str(staged),'hash':hashlib.sha256(b'new').hexdigest()}]}), encoding='utf-8')
            doc=module.WorkbenchDocument(html, root)
            self.assertEqual(html.read_text(), 'new'); self.assertFalse((support/'a.transaction.json').exists())


if __name__ == "__main__":
    unittest.main()
