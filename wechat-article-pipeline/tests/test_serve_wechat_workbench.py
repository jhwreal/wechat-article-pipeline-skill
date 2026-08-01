from __future__ import annotations

import importlib.util
import hashlib
import json
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock


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
    previous = sys.modules.get(spec.name)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
        if previous is None:
            sys.modules.pop(spec.name, None)
        else:
            sys.modules[spec.name] = previous
    return module


class WorkbenchTemplateTests(unittest.TestCase):
    def test_template_keeps_standalone_local_storage_and_adds_optional_server_save(self):
        source = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("localStorage.setItem", source)
        self.assertIn("/__wechat_workbench/save", source)
        self.assertIn("127.0.0.1", source)
        self.assertIn("localhost", source)
        self.assertIn("status.recovery_required", source)
        self.assertIn("response.status === 423", source)
        self.assertIn("status.manifest", source)
        self.assertIn("status.assets", source)
        self.assertIn("catch", source)

    def test_save_button_belongs_to_markdown_topbar_group_and_matches_primary_action(self):
        source = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('<div class="topbar-primary">', source)
        left = source.split('<div class="topbar-primary">', 1)[1].split('<div class="toolbar">', 1)[0]
        right = source.split('<div class="toolbar">', 1)[1].split('<div class="main">', 1)[0]
        self.assertIn('<button id="saveArticle" class="btn primary">保存</button>', left)
        self.assertNotIn('id="copyCurrentPlatform"', left)
        self.assertIn('id="platformMode"', right)
        self.assertIn('id="fontFamily"', right)
        self.assertIn('id="fontSize"', right)
        self.assertIn('id="themeColor"', right)
        self.assertLess(right.index('id="platformMode"'), right.index('id="fontFamily"'))
        self.assertIn('<option value="wechat" selected>微信格式</option>', right)
        self.assertIn('<option value="toutiao">头条格式</option>', right)
        self.assertIn('<option value="xiaohongshu">小红书格式</option>', right)
        self.assertIn('<button id="copyCurrentPlatform" class="btn primary">复制为微信格式</button>', right)
        self.assertNotIn('id="copyWechat"', right)
        self.assertNotIn('id="copyToutiao"', right)
        self.assertNotIn('id="copyXiaohongshu"', right)
        self.assertNotIn('id="saveArticle"', right)
        self.assertIn('grid-template-columns: 1.05fr .95fr', source)

    def test_toutiao_copy_has_platform_specific_cleanup_and_title_warning(self):
        source = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("normalizePlatformArticleRoot", source)
        self.assertIn("removePlatformArticleChrome", source)
        self.assertIn("removePlatformExternalLinks", source)
        self.assertIn("platformAdapter(target).headingMap", source)
        self.assertIn("platformUsesNativeSelection", source)
        self.assertIn("createSemanticArticleRoot(target, { forClipboard: true })", source)
        self.assertIn("titleLength > titleMax", source)
        self.assertIn("copyCurrentPlatformButton.addEventListener", source)
        self.assertIn("copyPlatformContent", source)
        self.assertIn("复制为头条格式", (ROOT / "references" / "platform-adapters.json").read_text(encoding="utf-8"))

    def test_xiaohongshu_copy_maps_headings_and_keeps_images_in_native_rich_html(self):
        source = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("platformAdapter(target).headingMap", source)
        self.assertIn("platformAdapter(target).imagePolicy", source)
        self.assertIn("applyHostedImagesForClipboard", source)
        self.assertIn("inlineImagesForClipboard", source)
        self.assertNotIn("wrapXiaohongshuImagesForClipboard", source)
        self.assertIn("PLATFORM_IMAGE_URLS.length !== images.length", source)
        self.assertIn("absolutizeImagesForClipboard", source)
        self.assertIn("copyBoxBySelection(box)", source)
        self.assertNotIn("data-xhs-image-marker", source)
        self.assertNotIn("[[XHS_IMAGE_", source)
        self.assertIn("copyCurrentPlatformButton.addEventListener", source)
        self.assertIn("titleLength > titleMax", source)
        self.assertIn("粘贴后仍需核验平台图片托管", source)
        self.assertIn("复制为小红书格式", (ROOT / "references" / "platform-adapters.json").read_text(encoding="utf-8"))


class WorkbenchDocumentTests(unittest.TestCase):
    def test_visual_staleness_tracks_relevant_text_until_asset_changes(self):
        module = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image = root / "body-1.png"
            image.write_bytes(b"first-image")
            visuals = {"body-1": {"path": str(image)}}
            original = "# 标题\n\n原来的判断。\n\n![配图]({{visual:body-1}})\n\n后文不相关。"
            edited = "# 标题\n\n修改后的判断。\n\n![配图]({{visual:body-1}})\n\n后文不相关。"

            first = module.inspect_visuals(original, visuals, job_dir=root)
            stale = module.inspect_visuals(
                edited, visuals, job_dir=root, baselines=first["baselines"]
            )
            still_stale = module.inspect_visuals(
                edited, visuals, job_dir=root, baselines=stale["baselines"]
            )
            image.write_bytes(b"regenerated-image")
            refreshed = module.inspect_visuals(
                edited, visuals, job_dir=root, baselines=still_stale["baselines"]
            )

            self.assertEqual(first["state"], "ready")
            self.assertEqual(stale["state"], "stale")
            self.assertEqual(still_stale["state"], "stale")
            self.assertEqual(refreshed["state"], "ready")

    def test_visual_fingerprints_support_embedded_images(self):
        module = load_server_module()
        result = module.inspect_visuals(
            "# 标题\n\n![题图]({{visual:cover}})",
            {"cover": {"data_uri": "data:image/png;base64,cG5n"}},
            job_dir=Path("."),
        )

        self.assertEqual(result["state"], "ready")
        self.assertTrue(result["baselines"]["cover"]["assetFingerprint"])

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
            for path in (html_path, markdown_path, job_path):
                path.chmod(0o640)
            document = module.WorkbenchDocument(html_path=html_path, workspace=workspace)
            payload = {
                "markdown": "# 最终稿\n\n![题图](../image/demo/cover.png)\n",
                "platformMode": "xiaohongshu",
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
            self.assertIn('"platformMode":"xiaohongshu"', saved_html)
            self.assertIn('"themeColor":"#123456"', saved_html)
            self.assertEqual(saved_markdown, "# 最终稿\n\n![题图]({{visual:cover}})\n")
            self.assertEqual(saved_job["article_markdown"], saved_markdown)
            for path in (html_path, markdown_path, job_path):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)

    def test_identical_save_is_a_noop_and_keeps_revision(self):
        module = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            html_path = workspace / "article.html"
            markdown = "# 标题\n\n正文。\n"
            template = TEMPLATE.read_text(encoding="utf-8")
            html_path.write_text(
                module.builder.apply_template(
                    {"article_markdown": markdown},
                    template,
                    markdown,
                ),
                encoding="utf-8",
            )
            document = module.WorkbenchDocument(html_path, workspace)
            before = hashlib.sha256(html_path.read_bytes()).hexdigest()

            result = document.save(
                {
                    "markdown": markdown,
                    "platformMode": "wechat",
                    "themeColor": "#17b394",
                    "fontSize": "16",
                    "fontFamily": '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif',
                }
            )
            document.close()

            self.assertTrue(result["saved"])
            self.assertTrue(result["unchanged"])
            self.assertEqual(result["revision"], 0)
            self.assertEqual(hashlib.sha256(html_path.read_bytes()).hexdigest(), before)

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
            staged.write_text('new', encoding='utf-8')
            (support/'a.transaction.json').write_text(json.dumps({'version':1,'revision':1,'files':[{'target':str(html),'staged':str(staged),'hash':hashlib.sha256(b'new').hexdigest()}]}), encoding='utf-8')
            doc=module.WorkbenchDocument(html, root)
            self.assertEqual(html.read_text(), 'new'); self.assertFalse((support/'a.transaction.json').exists())

    def test_transaction_recovery_rejects_targets_outside_workspace(self):
        module = load_server_module()
        with tempfile.TemporaryDirectory() as workspace_dir, tempfile.TemporaryDirectory() as outside_dir:
            root = Path(workspace_dir)
            html = root / "a.html"
            html.write_text("old", encoding="utf-8")
            outside = Path(outside_dir) / "do-not-touch.txt"
            outside.write_text("safe", encoding="utf-8")
            support = root / "support"
            staged = support / ".txn" / "1" / "a.html"
            staged.parent.mkdir(parents=True)
            staged.write_text("attacker", encoding="utf-8")
            (support / "a.transaction.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "revision": 1,
                        "files": [
                            {
                                "target": str(outside),
                                "staged": str(staged),
                                "hash": hashlib.sha256(b"attacker").hexdigest(),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            document = module.WorkbenchDocument(html, root)

            self.assertEqual(outside.read_text(encoding="utf-8"), "safe")
            self.assertTrue(document.status()["recovery_required"])
            self.assertIn("not allowed", document.status()["recovery_error"])

    def test_transaction_recovery_finishes_a_partially_committed_save(self):
        module = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            html = root / "a.html"
            markdown = root / "a.md"
            job = root / "a.job.json"
            html.write_text("new-html", encoding="utf-8")
            markdown.write_text("old-markdown", encoding="utf-8")
            job.write_text("old-job", encoding="utf-8")
            support = root / "support"
            transaction_dir = support / ".txn" / "2"
            transaction_dir.mkdir(parents=True)
            staged_html = transaction_dir / "a.html"
            staged_markdown = transaction_dir / "a.md"
            staged_job = transaction_dir / "a.job.json"
            staged_markdown.write_text("new-markdown", encoding="utf-8")
            staged_job.write_text("new-job", encoding="utf-8")
            entries = [
                {
                    "target": str(html),
                    "staged": str(staged_html),
                    "hash": hashlib.sha256(b"new-html").hexdigest(),
                },
                {
                    "target": str(markdown),
                    "staged": str(staged_markdown),
                    "hash": hashlib.sha256(b"new-markdown").hexdigest(),
                },
                {
                    "target": str(job),
                    "staged": str(staged_job),
                    "hash": hashlib.sha256(b"new-job").hexdigest(),
                },
            ]
            (support / "a.workbench-state.json").write_text(
                json.dumps(
                    {
                        "coreRevision": 1,
                        "manifest": {"state": "not_configured", "targetRevision": 1},
                        "assets": {},
                    }
                ),
                encoding="utf-8",
            )
            (support / "a.transaction.json").write_text(
                json.dumps({"version": 1, "revision": 2, "files": entries}), encoding="utf-8"
            )

            document = module.WorkbenchDocument(html, root)

            self.assertEqual(html.read_text(encoding="utf-8"), "new-html")
            self.assertEqual(markdown.read_text(encoding="utf-8"), "new-markdown")
            self.assertEqual(job.read_text(encoding="utf-8"), "new-job")
            self.assertEqual(document.status()["coreRevision"], 2)
            self.assertFalse(document.status().get("recovery_required", False))
            self.assertFalse((support / "a.transaction.json").exists())
            self.assertFalse((support / ".txn").exists())

    def test_stale_transaction_journal_cannot_roll_back_newer_files(self):
        module = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            html = root / "a.html"
            html.write_text("current", encoding="utf-8")
            support = root / "support"
            staged = support / ".txn" / "1" / "a.html"
            staged.parent.mkdir(parents=True)
            staged.write_text("stale", encoding="utf-8")
            (support / "a.workbench-state.json").write_text(
                json.dumps(
                    {
                        "coreRevision": 2,
                        "manifest": {"state": "not_configured", "targetRevision": 2},
                        "assets": {},
                    }
                ),
                encoding="utf-8",
            )
            (support / "a.transaction.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "revision": 1,
                        "files": [
                            {
                                "target": str(html),
                                "staged": str(staged),
                                "hash": hashlib.sha256(b"stale").hexdigest(),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            document = module.WorkbenchDocument(html, root)

            self.assertEqual(html.read_text(encoding="utf-8"), "current")
            self.assertTrue(document.status()["recovery_required"])
            self.assertIn("stale", document.status()["recovery_error"])

    def test_recovery_required_state_blocks_future_saves(self):
        module = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            html = root / "a.html"
            html.write_text("old", encoding="utf-8")
            support = root / "support"
            support.mkdir()
            missing = support / ".txn" / "1" / "a.html"
            (support / "a.transaction.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "revision": 1,
                        "files": [
                            {
                                "target": str(html),
                                "staged": str(missing),
                                "hash": hashlib.sha256(b"new").hexdigest(),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            document = module.WorkbenchDocument(html, root)

            with self.assertRaises(module.RecoveryRequired):
                document.save({"markdown": "new"})
            self.assertEqual(html.read_text(encoding="utf-8"), "old")

    def test_save_does_not_create_publish_manifest_when_not_configured(self):
        module = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            html = root / "a.html"
            html.write_text(
                "<script>const DEFAULT_MARKDOWN = `old`;"
                'const DEFAULT_WORKBENCH_STATE = {"themeColor":"#17b394","fontSize":"16","fontFamily":"sans-serif"};'
                "</script>",
                encoding="utf-8",
            )
            document = module.WorkbenchDocument(html, root)

            result = document.save({"markdown": "new"})

            self.assertTrue(result["saved"])
            self.assertEqual(result["manifest"]["state"], "not_configured")
            self.assertFalse((root / "a.publish-manifest.json").exists())
            self.assertEqual(list((root / "support").glob("a.job.r*.json")), [])

    def test_startup_reports_missing_job_assets_before_the_first_save(self):
        module = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            html = root / "a.html"
            job = root / "a.job.json"
            html.write_text("<html></html>", encoding="utf-8")
            job.write_text(
                json.dumps(
                    {
                        "article_markdown": "# 标题\n\n![题图]({{visual:cover}})",
                        "visuals": {"cover": {"path": "missing.png"}},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            document = module.WorkbenchDocument(html, root)
            status = document.status()
            document.close()

            self.assertEqual(status["assets"]["state"], "missing")
            self.assertEqual(status["assets"]["missingVisuals"], ["cover"])

    def test_manifest_worker_failure_does_not_strand_future_refreshes(self):
        module = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            html = root / "a.html"
            job = root / "a.job.json"
            manifest = root / "a.publish-manifest.json"
            html.write_text(
                "<script>const DEFAULT_MARKDOWN = `old`;"
                'const DEFAULT_WORKBENCH_STATE = {"themeColor":"#17b394","fontSize":"16","fontFamily":"sans-serif"};'
                "</script>",
                encoding="utf-8",
            )
            job.write_text(
                json.dumps({"article_markdown": "old", "visuals": {}}),
                encoding="utf-8",
            )
            manifest.write_text("{}", encoding="utf-8")
            document = module.WorkbenchDocument(html, root)
            attempted = threading.Event()

            def fail_refresh(_request):
                attempted.set()
                raise TimeoutError("manifest helper timed out")

            document._refresh_manifest = fail_refresh
            document.save({"markdown": "new"})
            self.assertTrue(attempted.wait(timeout=1))
            for _ in range(100):
                with document._lock:
                    if document._manifest_thread is None:
                        break
                time.sleep(0.005)

            self.assertIsNone(document._manifest_thread)
            self.assertEqual(document.status()["manifest"]["state"], "failed")
            self.assertIn("TimeoutError", document.status()["manifest"]["error"])

    def test_pending_manifest_refresh_resumes_after_restart(self):
        module = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            html = root / "a.html"
            job = root / "a.job.json"
            manifest = root / "a.publish-manifest.json"
            support = root / "support"
            support.mkdir()
            html.write_text("<html></html>", encoding="utf-8")
            job.write_text(
                json.dumps({"article_markdown": "# 新稿", "visuals": {}}),
                encoding="utf-8",
            )
            manifest.write_text(
                json.dumps(
                    {
                        "article_slug": "saved-slug",
                        "author": "显式作者",
                        "env_file": "missing.env",
                        "account": {"selector": "", "alias": "", "name": ""},
                        "preview": {"account": "preview-user"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (support / "a.workbench-state.json").write_text(
                json.dumps(
                    {
                        "coreRevision": 3,
                        "manifest": {"state": "pending", "targetRevision": 3},
                        "assets": {},
                    }
                ),
                encoding="utf-8",
            )
            attempted = threading.Event()
            captured = []
            original_refresh = module.WorkbenchDocument._refresh_manifest

            def record_refresh(_document, request):
                captured.append(request)
                attempted.set()
                return True, "ok"

            module.WorkbenchDocument._refresh_manifest = record_refresh
            try:
                document = module.WorkbenchDocument(html, root)
                self.assertTrue(attempted.wait(timeout=1))
                document.close()
            finally:
                module.WorkbenchDocument._refresh_manifest = original_refresh

            self.assertEqual(len(captured), 1)
            request = captured[0]
            self.assertEqual(request.revision, 3)
            self.assertEqual(request.article_slug, "saved-slug")
            self.assertEqual(request.account_selector, "default")
            self.assertEqual(request.author, "显式作者")
            self.assertEqual(request.preview_account, "preview-user")
            self.assertTrue(request.job_snapshot.exists())

    def test_manifest_snapshot_absolutizes_relative_visual_paths(self):
        module = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            html = root / "a.html"
            image = root / "images" / "cover.png"
            image.parent.mkdir()
            html.write_text("<html></html>", encoding="utf-8")
            image.write_bytes(b"image")
            document = module.WorkbenchDocument(html, root)

            snapshot_text = document._manifest_snapshot_text(
                json.dumps(
                    {
                        "article_markdown": "# 标题",
                        "visuals": {"cover": {"path": "images/cover.png"}},
                    }
                )
            )
            document.close()

            snapshot = json.loads(snapshot_text)
            self.assertEqual(
                snapshot["visuals"]["cover"]["path"],
                str(image.resolve()),
            )

    def test_manifest_refresh_preserves_explicit_metadata_without_existing_env_file(self):
        module = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            html = root / "a.html"
            job = root / "a.job.json"
            manifest = root / "a.publish-manifest.json"
            html.write_text("<html></html>", encoding="utf-8")
            job.write_text("{}", encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {
                        "article_slug": "slug",
                        "author": "显式作者",
                        "env_file": str(root / "does-not-exist.env"),
                        "account": {"selector": "", "alias": "", "name": ""},
                        "preview": {"account": "preview-user"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            document = module.WorkbenchDocument(html, root)
            document._state["coreRevision"] = 1
            request = document._manifest_refresh_request(1, job, None)
            commands = []
            original_run = module.subprocess.run

            def fake_run(command, **_kwargs):
                commands.append(command)
                Path(command[3]).write_text("{}", encoding="utf-8")
                return module.subprocess.CompletedProcess(command, 0, "", "")

            module.subprocess.run = fake_run
            try:
                refreshed, message = document._refresh_manifest(request)
            finally:
                module.subprocess.run = original_run
                document.close()

            self.assertTrue(refreshed, message)
            self.assertIn("--account", commands[0])
            self.assertIn("default", commands[0])
            self.assertIn("--author", commands[0])
            self.assertIn("显式作者", commands[0])
            self.assertIn("--preview-account", commands[0])
            self.assertIn("preview-user", commands[0])

    def test_manifest_refresh_keeps_only_metadata_and_embeds_source_state_in_helper(self):
        module = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            html = root / "a.html"
            job = root / "a.job.json"
            manifest = root / "a.publish-manifest.json"
            html.write_text("<html></html>", encoding="utf-8")
            job.write_text("{}", encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {
                        "article_slug": "slug",
                        "author": "作者",
                        "env_file": str(root / ".env"),
                        "account": {"selector": "default", "alias": "", "name": "账号"},
                        "preview": {"account": "preview-user"},
                        "content_html": "large-payload",
                        "image_candidates": [{"src": "large-payload"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            document = module.WorkbenchDocument(html, root)
            self.assertNotIn("content_html", document._manifest_meta)
            self.assertNotIn("image_candidates", document._manifest_meta)
            document._state["coreRevision"] = 2
            request = document._manifest_refresh_request(
                2,
                job,
                {
                    "core_revision": 2,
                    "asset_state": "ready",
                    "stale_visuals": [],
                    "missing_visuals": [],
                },
            )
            commands = []
            original_run = module.subprocess.run

            def fake_run(command, **_kwargs):
                commands.append(command)
                Path(command[3]).write_text("{}", encoding="utf-8")
                return module.subprocess.CompletedProcess(command, 0, "", "")

            module.subprocess.run = fake_run
            try:
                refreshed, message = document._refresh_manifest(request)
            finally:
                module.subprocess.run = original_run
                document.close()

            self.assertTrue(refreshed, message)
            state_index = commands[0].index("--source-state-json") + 1
            source_state = json.loads(commands[0][state_index])
            self.assertEqual(source_state["core_revision"], 2)
            self.assertEqual(source_state["manifest_revision"], 2)

    def test_compact_manifest_header_avoids_loading_the_large_payload(self):
        module = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = Path(temp_dir) / "a.publish-manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "workbench_refresh": {
                            "article_slug": "slug",
                            "author": "作者",
                            "env_file": "/tmp/test.env",
                            "account": {"selector": "default", "alias": "", "name": "账号"},
                            "preview": {"account": "preview-user"},
                        },
                        "content_html": "x" * 100_000,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with mock.patch.object(
                Path,
                "read_text",
                side_effect=AssertionError("large manifest fallback should not run"),
            ):
                metadata = module.load_manifest_refresh_metadata(manifest)

            self.assertEqual(metadata["article_slug"], "slug")
            self.assertEqual(metadata["account"]["selector"], "default")
            self.assertEqual(metadata["preview"]["account"], "preview-user")

    def test_stale_missing_manifest_input_does_not_overwrite_newer_state(self):
        module = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            html = root / "a.html"
            manifest = root / "a.publish-manifest.json"
            html.write_text("<html></html>", encoding="utf-8")
            manifest.write_text("{}", encoding="utf-8")
            document = module.WorkbenchDocument(html, root)
            document._state["coreRevision"] = 2
            document._state["manifest"] = {"state": "pending", "targetRevision": 2}
            request = module.ManifestRefreshRequest(
                revision=1,
                job_snapshot=root / "missing.job.json",
                manifest_path=manifest,
                env_file=root / "missing.env",
            )

            refreshed, message = document._refresh_manifest(request)
            document.close()

            self.assertFalse(refreshed)
            self.assertEqual(message, "stale-candidate")
            self.assertEqual(
                document.status()["manifest"],
                {"state": "pending", "targetRevision": 2},
            )

    def test_static_files_reject_untrusted_host_headers(self):
        module = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            html = root / "a.html"
            html.write_text("safe", encoding="utf-8")
            document = module.WorkbenchDocument(html, root)
            handler_class = module.make_handler(document)
            handler = handler_class.__new__(handler_class)
            handler.headers = {"Host": "attacker.example"}
            handler.server = type("Server", (), {"server_address": ("127.0.0.1", 8765)})()
            handler.path = "/a.html"
            responses = []
            handler.send_json = lambda status, payload: responses.append((status, payload))

            handler.do_GET()

            head_responses = []
            handler.send_response = lambda status: head_responses.append(status)
            handler.send_header = lambda *_args: None
            handler.end_headers = lambda: None
            handler.do_HEAD()
            document.close()

            self.assertEqual(responses, [(403, {"error": "invalid host"})])
            self.assertEqual(head_responses, [403])
            self.assertTrue(module.is_allowed_host("LOCALHOST:8765", 8765))
            self.assertTrue(module.is_allowed_host("127.0.0.1:8765", 8765))
            self.assertFalse(module.is_allowed_host("attacker.example", 8765))

    def test_static_responses_add_local_security_and_cache_headers(self):
        module = load_server_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            html = root / "a.html"
            html.write_text("safe", encoding="utf-8")
            document = module.WorkbenchDocument(html, root)
            handler_class = module.make_handler(document)
            handler = handler_class.__new__(handler_class)
            handler.path = "/a.html"
            headers = []
            handler.send_header = lambda name, value: headers.append((name, value))

            with mock.patch.object(
                module.SimpleHTTPRequestHandler,
                "end_headers",
                lambda _handler: None,
            ):
                handler.end_headers()
            document.close()

            header_map = dict(headers)
            self.assertEqual(header_map["X-Frame-Options"], "DENY")
            self.assertEqual(header_map["Cache-Control"], "no-store")
            self.assertIn("default-src 'self'", header_map["Content-Security-Policy"])
            self.assertIn("object-src 'none'", header_map["Content-Security-Policy"])


if __name__ == "__main__":
    unittest.main()
