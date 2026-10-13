from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "wechat-article-pipeline" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import article_identity as identity
import make_wechat_publish_manifest as manifest_builder
import platform_delivery_state as delivery
import publish_wechat_api as publisher
from workbench_document import WorkbenchDocument


PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR42mNk+M/wHwAF/gL+IpcQ3wAAAABJRU5ErkJggg=="


class PublishSourceSnapshotTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.markdown = self.root / "article.md"
        self.html = self.root / "article.html"
        self.job_path = self.root / "article.job.json"
        self.manifest_path = self.root / "article.publish-manifest.json"
        self.receipt = self.root / "receipt.json"
        self.env = self.root / "fake.env"
        self.env.write_text("WECHAT_AUTHOR=作者\n", encoding="utf-8")
        self.config = self.root / "missing-config.json"
        self.markdown.write_text("# 标题\n\n旧正文。", encoding="utf-8")
        self.html.write_text("<html></html>", encoding="utf-8")

    def inputs(self, *, snapshot=True, workbench=True):
        job = {"article_markdown": self.markdown.read_text(encoding="utf-8"), "visuals": {}}
        if snapshot:
            job["source_markdown"] = identity.markdown_source_snapshot(self.markdown)
        self.job_path.write_text(json.dumps(job), encoding="utf-8")
        manifest = {
            "title": "标题", "digest": "摘要", "content_html": "<p>旧正文。</p>",
            "cover": {"src": "data:image/png;base64," + PNG},
            "source_job": str(self.job_path),
            "source_fingerprint": identity.compute_source_fingerprint(job, self.root),
        }
        if workbench:
            manifest["workbench_html"] = str(self.html)
        if snapshot:
            manifest.update(identity.source_markdown_receipt(job, self.root, self.markdown))
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest

    def invoke(self, *options, changes=None):
        argv = ["publisher", str(self.manifest_path), "--env-file", str(self.env),
                "--config", str(self.config), "--token-cache", str(self.root / "cache.json"),
                "--out", str(self.receipt), *options]
        fakes = {
            "request_json": Mock(side_effect=AssertionError("network forbidden")),
            "get_access_token": Mock(return_value="fake-token"),
            "upload_body_images": Mock(side_effect=lambda content, token: (content, [])),
            "upload_cover": Mock(return_value={"thumb_media_id": "fake-thumb", "width": "10", "height": "10"}),
            "create_draft": Mock(return_value="fake-draft"),
            "verify_draft": Mock(return_value={"verified": True, "table_count": 0, "title": "标题"}),
        }
        fakes.update(changes or {})
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(sys, "argv", argv))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            for name, replacement in fakes.items():
                stack.enter_context(patch.object(publisher, name, replacement))
            publisher.main()
        return json.loads(self.receipt.read_text(encoding="utf-8")), fakes

    def test_changed_markdown_blocks_legacy_and_new_manifests_before_network(self):
        for snapshot in (False, True):
            for workbench in (False, True):
                for mode in ("--dry-run", "--create-draft"):
                    with self.subTest(snapshot=snapshot, workbench=workbench, mode=mode):
                        self.markdown.write_text("# 标题\n\n旧正文。", encoding="utf-8")
                        self.inputs(snapshot=snapshot, workbench=workbench)
                        self.markdown.write_text("# 标题\n\n新正文。", encoding="utf-8")
                        token = Mock(side_effect=AssertionError("must fail before token request"))
                        with self.assertRaisesRegex(SystemExit, "stale"):
                            self.invoke(mode, changes={"get_access_token": token})
                        token.assert_not_called()
                        self.assertFalse(self.receipt.exists())

    def test_new_snapshot_rejects_deleted_source_and_formatting_only_edits(self):
        self.inputs()
        self.markdown.write_text("# 标题\n\n**旧正文。**", encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "source Markdown changed"):
            self.invoke("--create-draft")
        self.markdown.unlink()
        with self.assertRaises(SystemExit):
            self.invoke("--create-draft")

    def test_legacy_placeholder_and_relative_image_representations_match(self):
        image = self.root / "cover.png"
        image.write_bytes(base64.b64decode(PNG))
        self.markdown.write_text("# 标题\n\n![题图](cover.png)\n\n正文。\n", encoding="utf-8")
        job = {"article_markdown": "# 标题\n\n![题图]({{visual:cover}})\n\n正文。",
               "visuals": {"cover": {"path": str(image)}}}
        self.job_path.write_text(json.dumps(job), encoding="utf-8")
        manifest = {"workbench_html": str(self.html),
                    "source_fingerprint": identity.compute_source_fingerprint(job, self.root)}
        receipt = identity.validate_source_freshness(manifest)
        self.assertEqual(receipt["delivery_source_fingerprint"], identity.delivery_source_fingerprint(self.markdown))

    def test_unproven_legacy_focus_transformation_requires_repackaging(self):
        manifest = self.inputs(snapshot=False)
        job = json.loads(self.job_path.read_text(encoding="utf-8"))
        job["article_markdown"] = "# 标题\n\n**旧正文。**"
        self.job_path.write_text(json.dumps(job), encoding="utf-8")
        manifest["source_fingerprint"] = identity.compute_source_fingerprint(job, self.root)
        with self.assertRaisesRegex(ValueError, "regenerate the article package"):
            identity.validate_source_freshness(manifest)

    def test_changes_after_upload_starts_never_relabel_old_draft_as_new_source(self):
        manifest = self.inputs()
        original_manifest_hash = hashlib.sha256(self.manifest_path.read_bytes()).hexdigest()

        def begin_upload(*_args):
            self.markdown.write_text("# 标题\n\n后来改好的新正文。", encoding="utf-8")
            self.manifest_path.write_text(json.dumps({**manifest, "content_html": "<p>新正文。</p>"}), encoding="utf-8")
            return "fake-token"

        receipt, calls = self.invoke("--create-draft", "--verify-draft", changes={"get_access_token": Mock(side_effect=begin_upload)})
        self.assertEqual(calls["create_draft"].call_args.args[0]["articles"][0]["content"], "<p>旧正文。</p>")
        self.assertEqual(receipt["delivery_source_fingerprint"], manifest["delivery_source_fingerprint"])
        self.assertEqual(receipt["manifest_sha256"], original_manifest_hash)
        self.assertNotEqual(receipt["delivery_source_fingerprint"], identity.delivery_source_fingerprint(self.markdown))
        current = delivery.new_state("article", "标题", self.markdown)
        with self.assertRaisesRegex(ValueError, "revision"):
            delivery.record_result(current, "wechat", receipt, self.receipt)

    def test_second_preflight_blocks_change_before_first_network_operation(self):
        self.inputs()
        original_validate = identity.validate_source_freshness
        calls = 0

        def validate(manifest):
            nonlocal calls
            result = original_validate(manifest)
            calls += 1
            if calls == 1:
                self.markdown.write_text("# 标题\n\n并发修改。", encoding="utf-8")
            return result

        token = Mock()
        with patch.object(publisher, "validate_source_freshness", side_effect=validate):
            with self.assertRaisesRegex(SystemExit, "source Markdown changed"):
                self.invoke("--create-draft", changes={"get_access_token": token})
        token.assert_not_called()

    def test_resume_keeps_original_source_receipt_after_local_edit(self):
        manifest = self.inputs()
        with self.assertRaisesRegex(RuntimeError, "temporary verification failure"):
            self.invoke("--create-draft", "--verify-draft", changes={
                "verify_draft": Mock(side_effect=RuntimeError("temporary verification failure")),
            })
        self.markdown.write_text("# 标题\n\n新正文。", encoding="utf-8")
        receipt, calls = self.invoke("--create-draft", "--resume")
        self.assertEqual(receipt["delivery_source_fingerprint"], manifest["delivery_source_fingerprint"])
        calls["create_draft"].assert_not_called()

    def test_standalone_legacy_manifest_has_no_live_markdown_attestation(self):
        manifest = self.inputs()
        for key in ("source_job", "workbench_html", "source_fingerprint", "source_markdown", "delivery_source_fingerprint"):
            manifest.pop(key, None)
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.markdown.write_text("# 新稿\n\n另一个版本。", encoding="utf-8")
        receipt, _calls = self.invoke("--create-draft")
        self.assertEqual(receipt["status"], "success")
        self.assertNotIn("delivery_source_fingerprint", receipt)

    def test_manifest_builder_rejects_source_change_during_render(self):
        self.inputs()
        output = self.root / "candidate.json"
        original = manifest_builder.embed_local_markdown_images

        def change_source(markdown, job_dir):
            self.markdown.write_text("# 标题\n\n并发修改。", encoding="utf-8")
            return original(markdown, job_dir)

        argv = ["manifest", str(self.job_path), str(output), "--workbench-html", str(self.html),
                "--env-file", str(self.env), "--config", str(self.config)]
        with patch.object(sys, "argv", argv), patch.object(manifest_builder, "embed_local_markdown_images", side_effect=change_source), \
                patch.object(manifest_builder, "select_cover_candidate", return_value=({"src": "data:image/png;base64," + PNG}, [])), \
                patch.object(manifest_builder, "build_wechat_cover_manifest", return_value={}):
            with self.assertRaisesRegex(SystemExit, "source Markdown changed"):
                manifest_builder.main()
        self.assertFalse(output.exists())

    def test_real_pipeline_focus_marking_and_image_transformations_preserve_snapshot(self):
        images = self.root / "image" / "article"
        images.mkdir(parents=True)
        for name in ("cover", "body-1", "closing"):
            (images / (name + ".png")).write_bytes(base64.b64decode(PNG))
        article = ("# 标题\n\n![题图]({{visual:cover}})\n\n"
                   "第1段，真正重要的是这里应该独立出现一个重点句，而不是全部合并在最后。\n\n"
                   "![正文图]({{visual:body-1}})\n\n再给出一个能直接执行的方法。\n\n"
                   "![尾图]({{visual:closing}})\n")
        self.markdown.write_text(article, encoding="utf-8")
        for no_images in (False, True):
            with self.subTest(no_images=no_images):
                command = [sys.executable, str(SCRIPTS / "postprocess_wechat_article.py"),
                           str(self.markdown), str(self.html), "--workspace", str(self.root),
                           "--article-slug", "article", "--publish-manifest", "--publisher-env-file", str(self.env),
                           "--publisher-config", str(self.config), "--focus-target-chars", "30"]
                if no_images:
                    command += ["--no-images", "--cover-image", str(images / "cover.png")]
                result = subprocess.run(command, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                job = json.loads(self.job_path.read_text(encoding="utf-8"))
                self.assertEqual(job["source_markdown"], identity.markdown_source_snapshot(self.markdown))
                self.assertNotEqual(job["article_markdown"], self.markdown.read_text(encoding="utf-8"))
                receipt, _calls = self.invoke("--dry-run")
                self.assertEqual(receipt["delivery_source_fingerprint"], identity.delivery_source_fingerprint(self.markdown))

    def package_without_body_images(self):
        cover = self.root / "cover.png"
        cover.write_bytes(base64.b64decode(PNG))
        command = [sys.executable, str(SCRIPTS / "package_wechat_article_bundle.py"),
                   str(self.markdown), str(self.html), "--no-images", "--cover-image", str(cover),
                   "--publish-manifest", "--publisher-env-file", str(self.env),
                   "--publisher-config", str(self.config)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_complete_rebuild_after_browser_save_accepts_ready_sidecar_only(self):
        self.package_without_body_images()
        document = WorkbenchDocument(self.html, self.root)
        try:
            document.save({"markdown": "# 标题\n\n浏览器保存的新稿。"})
            if document._manifest_thread:
                document._manifest_thread.join(timeout=10)
            self.assertEqual(document.status()["manifest"]["state"], "ready")
            identity.validate_source_freshness(json.loads(self.manifest_path.read_text(encoding="utf-8")))
        finally:
            document.close()
        self.package_without_body_images()
        receipt, _calls = self.invoke("--dry-run")
        self.assertEqual(receipt["delivery_source_fingerprint"], identity.delivery_source_fingerprint(self.markdown))
        sidecar = self.root / "support" / "article.workbench-state.json"
        ready = json.loads(sidecar.read_text(encoding="utf-8"))
        self.assertGreater(ready["coreRevision"], 0)
        self.assertNotIn("source_state", json.loads(self.manifest_path.read_text(encoding="utf-8")))
        for change in ({"manifest": {"state": "failed"}}, {"manifest": {"state": "pending"}}, {"recovery_required": True}):
            sidecar.write_text(json.dumps({**ready, **change}), encoding="utf-8")
            with self.subTest(change=change), self.assertRaisesRegex(SystemExit, "incomplete"):
                self.invoke("--dry-run")

    def test_direct_package_preserves_crlf_front_matter_and_source_bytes(self):
        self.markdown.write_bytes("---\r\ncategory: note\r\n---\r\n# 标题\r\n\r\n正文。\r\n".encode("utf-8"))
        self.package_without_body_images()
        job = json.loads(self.job_path.read_text(encoding="utf-8"))
        self.assertNotIn("category:", job["article_markdown"])
        self.assertEqual(job["source_markdown"], identity.markdown_source_snapshot(self.markdown))
        self.invoke("--dry-run")


if __name__ == "__main__":
    unittest.main()
