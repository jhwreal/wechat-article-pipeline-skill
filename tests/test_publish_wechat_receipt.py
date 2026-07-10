#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import hashlib
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "wechat-article-pipeline" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import publish_wechat_api as publisher  # noqa: E402


PNG_1X1 = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lpI1GQAAAABJRU5ErkJggg=="
)


class PublishWechatReceiptTest(unittest.TestCase):
    def make_inputs(self, root: Path, *, include_issue: bool = False) -> tuple[Path, Path, Path]:
        manifest = root / "article.publish-manifest.json"
        result = root / "article.wechat-api-result.json"
        env_file = root / ".env"
        env_file.write_text("WECHAT_ORIGINAL_ISSUE=9\n", encoding="utf-8")
        payload: dict[str, Any] = {
            "title": "标题",
            "author": "作者",
            "digest": "摘要",
            "content_html": "<p>正文第一段。</p>",
            "cover": {"src": PNG_1X1},
        }
        if include_issue:
            payload["article_signature"] = {
                "issue_env_key": "WECHAT_ORIGINAL_ISSUE",
                "issue": "9",
            }
        manifest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return manifest, result, env_file

    @staticmethod
    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("network or skipped draft setup was invoked")

    @staticmethod
    def fake_upload_body(content_html: str, _access_token: str) -> tuple[str, list[dict[str, str]]]:
        return content_html, []

    @staticmethod
    def fake_upload_cover(_manifest: dict[str, Any], _access_token: str) -> dict[str, str]:
        return {
            "thumb_media_id": "thumb-123",
            "url": "https://example.invalid/cover.png",
            "width": "900",
            "height": "383",
            "local_path_removed": "true",
        }

    @staticmethod
    def fake_create_draft(_payload: dict[str, Any], _access_token: str) -> str:
        return "media-123"

    @staticmethod
    def fake_verify_draft(_media_id: str, expected_title: str, _access_token: str) -> dict[str, Any]:
        return {"verified": True, "title": expected_title, "article_count": 1}

    @staticmethod
    def fake_send_preview(
        _media_id: str,
        _args: Any,
        _manifest: dict[str, Any],
        _account: dict[str, str],
        _access_token: str,
    ) -> dict[str, Any]:
        return {"msg_id": 42}

    def invoke(
        self,
        manifest: Path,
        result: Path,
        env_file: Path,
        *extra_args: str,
        replacements: dict[str, Callable[..., Any] | mock.Mock] | None = None,
    ) -> None:
        argv = [
            "publish_wechat_api.py",
            str(manifest),
            "--create-draft",
            "--access-token",
            "test-token",
            "--env-file",
            str(env_file),
            "--out",
            str(result),
            *extra_args,
        ]
        fakes: dict[str, Callable[..., Any] | mock.Mock] = {
            "upload_body_images": self.fake_upload_body,
            "upload_cover": self.fake_upload_cover,
            "create_draft": self.fake_create_draft,
            "verify_draft": self.fake_verify_draft,
            "send_preview": self.fake_send_preview,
        }
        fakes.update(replacements or {})
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(sys, "argv", argv))
            stack.enter_context(mock.patch.object(publisher, "request_json", side_effect=self.forbidden))
            for name, replacement in fakes.items():
                stack.enter_context(mock.patch.object(publisher, name, new=replacement))
            publisher.main()

    def test_draft_receipt_exists_before_verify_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest, result_path, env_file = self.make_inputs(Path(tmp_dir))

            def fake_verify(media_id: str, expected_title: str, access_token: str) -> dict[str, Any]:
                receipt = json.loads(result_path.read_text(encoding="utf-8"))
                self.assertEqual(receipt["draft_media_id"], "media-123")
                self.assertEqual(receipt["status"], "partial_success")
                self.assertEqual(receipt["operation_state"]["draft_add"]["state"], "succeeded")
                raise RuntimeError("verify stopped")

            with self.assertRaisesRegex(RuntimeError, "verify stopped"):
                self.invoke(
                    manifest,
                    result_path,
                    env_file,
                    "--verify-draft",
                    replacements={"verify_draft": fake_verify},
                )

    def test_verify_failure_preserves_partial_success_and_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest, result_path, env_file = self.make_inputs(Path(tmp_dir))

            def fail_verify(_media_id: str, _expected_title: str, _access_token: str) -> dict[str, Any]:
                raise RuntimeError("verification unavailable")

            with self.assertRaisesRegex(RuntimeError, "verification unavailable"):
                self.invoke(
                    manifest,
                    result_path,
                    env_file,
                    "--verify-draft",
                    replacements={"verify_draft": fail_verify},
                )

            receipt = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "partial_success")
            self.assertEqual(receipt["draft_media_id"], "media-123")
            self.assertEqual(receipt["operation_state"]["verify_draft"]["state"], "failed")
            self.assertIn("verification unavailable", receipt["last_error"]["message"])

    def test_resume_skips_upload_and_draft_add(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest, result_path, env_file = self.make_inputs(Path(tmp_dir))

            def fail_verify(_media_id: str, _expected_title: str, _access_token: str) -> dict[str, Any]:
                raise RuntimeError("retry me")

            with self.assertRaisesRegex(RuntimeError, "retry me"):
                self.invoke(
                    manifest,
                    result_path,
                    env_file,
                    "--verify-draft",
                    replacements={"verify_draft": fail_verify},
                )

            skipped_upload = mock.Mock(side_effect=self.forbidden)
            skipped_cover = mock.Mock(side_effect=self.forbidden)
            skipped_draft_add = mock.Mock(side_effect=self.forbidden)
            verify = mock.Mock(return_value={"verified": True, "title": "标题", "article_count": 1})
            self.invoke(
                manifest,
                result_path,
                env_file,
                "--resume",
                replacements={
                    "upload_body_images": skipped_upload,
                    "upload_cover": skipped_cover,
                    "create_draft": skipped_draft_add,
                    "verify_draft": verify,
                },
            )

            skipped_upload.assert_not_called()
            skipped_cover.assert_not_called()
            skipped_draft_add.assert_not_called()
            verify.assert_called_once_with("media-123", "标题", "test-token")
            receipt = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "success")
            self.assertEqual(receipt["draft_media_id"], "media-123")

    def test_unknown_preview_requires_retry_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest, result_path, env_file = self.make_inputs(Path(tmp_dir))

            def lose_preview_response(
                _media_id: str,
                _args: Any,
                _manifest: dict[str, Any],
                _account: dict[str, str],
                _access_token: str,
            ) -> dict[str, Any]:
                raise RuntimeError("preview response lost")

            with self.assertRaisesRegex(RuntimeError, "preview response lost"):
                self.invoke(
                    manifest,
                    result_path,
                    env_file,
                    "--send-preview",
                    "--preview-account",
                    "preview-user",
                    replacements={"send_preview": lose_preview_response},
                )

            receipt = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "partial_success")
            self.assertEqual(receipt["operation_state"]["send_preview"]["state"], "unknown")

            preview = mock.Mock(return_value={"msg_id": 42})
            with self.assertRaisesRegex(SystemExit, "--retry-preview"):
                self.invoke(
                    manifest,
                    result_path,
                    env_file,
                    "--resume",
                    "--preview-account",
                    "preview-user",
                    replacements={
                        "upload_body_images": self.forbidden,
                        "upload_cover": self.forbidden,
                        "create_draft": self.forbidden,
                        "send_preview": preview,
                    },
                )
            preview.assert_not_called()

            self.invoke(
                manifest,
                result_path,
                env_file,
                "--resume",
                "--retry-preview",
                "--preview-account",
                "preview-user",
                replacements={
                    "upload_body_images": self.forbidden,
                    "upload_cover": self.forbidden,
                    "create_draft": self.forbidden,
                    "send_preview": preview,
                },
            )
            preview.assert_called_once()
            receipt = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "success")
            self.assertEqual(receipt["preview"], {"msg_id": 42})

    def test_resume_binds_stored_preview_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest, result_path, env_file = self.make_inputs(Path(tmp_dir))

            def lose_preview_response(
                _media_id: str,
                _args: Any,
                _manifest: dict[str, Any],
                _account: dict[str, str],
                _access_token: str,
            ) -> dict[str, Any]:
                raise RuntimeError("preview response lost")

            with self.assertRaisesRegex(RuntimeError, "preview response lost"):
                self.invoke(
                    manifest,
                    result_path,
                    env_file,
                    "--send-preview",
                    "--preview-account",
                    "original-preview-user",
                    replacements={"send_preview": lose_preview_response},
                )

            receipt = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(
                receipt["operation_state"]["send_preview"]["parameters"]["target"],
                {"kind": "account", "value": "original-preview-user"},
            )

            preview = mock.Mock(return_value={"msg_id": 42})
            with self.assertRaisesRegex(SystemExit, "preview target"):
                self.invoke(
                    manifest,
                    result_path,
                    env_file,
                    "--resume",
                    "--retry-preview",
                    "--preview-account",
                    "different-preview-user",
                    replacements={"send_preview": preview},
                )
            preview.assert_not_called()

            def assert_stored_target(
                _media_id: str,
                args: Any,
                _manifest: dict[str, Any],
                _account: dict[str, str],
                _access_token: str,
            ) -> dict[str, Any]:
                self.assertEqual(args.preview_account, "original-preview-user")
                self.assertIsNone(args.preview_openid)
                return {"msg_id": 42}

            self.invoke(
                manifest,
                result_path,
                env_file,
                "--resume",
                "--retry-preview",
                replacements={"send_preview": assert_stored_target},
            )

    def test_resume_rejects_changed_env_file_before_issue_increment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            manifest, result_path, original_env = self.make_inputs(root, include_issue=True)
            original_env.write_text("WECHAT_ORIGINAL_ISSUE=11\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "conflict"):
                self.invoke(
                    manifest,
                    result_path,
                    original_env,
                    "--increment-original-issue",
                )

            other_env = root / "other.env"
            other_env.write_text("WECHAT_ORIGINAL_ISSUE=9\n", encoding="utf-8")
            before_original = original_env.read_bytes()
            before_other = other_env.read_bytes()
            with self.assertRaisesRegex(SystemExit, "env_file"):
                self.invoke(manifest, result_path, other_env, "--resume")

            self.assertEqual(original_env.read_bytes(), before_original)
            self.assertEqual(other_env.read_bytes(), before_other)

    def test_draft_add_without_media_id_cannot_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest, result_path, env_file = self.make_inputs(Path(tmp_dir))
            receipt = {
                "manifest": str(manifest.resolve()),
                "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                "dry_run": False,
                "account": {"selector": "", "alias": "", "name": ""},
                "status": "unknown",
                "operation_state": {"draft_add": {"requested": True, "state": "in_progress"}},
                "last_error": None,
            }
            result_path.write_text(json.dumps(receipt), encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "media_id"):
                self.invoke(
                    manifest,
                    result_path,
                    env_file,
                    "--resume",
                    replacements={
                        "upload_body_images": self.forbidden,
                        "upload_cover": self.forbidden,
                        "create_draft": self.forbidden,
                    },
                )

            receipt = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "unknown")
            self.assertEqual(receipt["operation_state"]["draft_add"]["state"], "unknown")

    def test_new_run_refuses_to_overwrite_existing_journal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest, result_path, env_file = self.make_inputs(Path(tmp_dir))
            old_receipt = {
                "manifest": str(manifest.resolve()),
                "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                "dry_run": False,
                "account": {"selector": "", "alias": "", "name": ""},
                "status": "success",
                "operation_state": {"draft_add": {"requested": True, "state": "succeeded"}},
                "last_error": None,
                "draft_media_id": "old-media-id",
            }
            result_path.write_text(json.dumps(old_receipt, indent=2) + "\n", encoding="utf-8")
            before = result_path.read_bytes()

            with self.assertRaisesRegex(SystemExit, "--resume"):
                self.invoke(manifest, result_path, env_file)

            self.assertEqual(result_path.read_bytes(), before)
            self.assertEqual(json.loads(result_path.read_text(encoding="utf-8"))["draft_media_id"], "old-media-id")

    def test_success_keeps_legacy_result_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest, result_path, env_file = self.make_inputs(Path(tmp_dir), include_issue=True)
            self.invoke(
                manifest,
                result_path,
                env_file,
                "--verify-draft",
                "--send-preview",
                "--preview-account",
                "preview-user",
                "--increment-original-issue",
            )

            receipt = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "success")
            self.assertEqual(receipt["draft_media_id"], "media-123")
            self.assertEqual(receipt["draft_verification"]["verified"], True)
            self.assertEqual(receipt["preview"], {"msg_id": 42})
            self.assertEqual(receipt["original_issue_increment"]["next_issue"], "10")

    def test_atomic_write_preserves_previous_destination_on_failure(self) -> None:
        atomic_files = importlib.import_module("atomic_files")
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            destination = root / "receipt.json"
            destination.write_text("previous\n", encoding="utf-8")

            with mock.patch.object(atomic_files.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    atomic_files.atomic_write_text(destination, "new\n")

            self.assertEqual(destination.read_text(encoding="utf-8"), "previous\n")
            self.assertEqual(list(root.glob(".receipt.json.*.tmp")), [])

    def test_atomic_write_json_accepts_generic_mapping(self) -> None:
        atomic_files = importlib.import_module("atomic_files")
        with tempfile.TemporaryDirectory() as tmp_dir:
            destination = Path(tmp_dir) / "receipt.json"
            atomic_files.atomic_write_json(destination, MappingProxyType({"title": "标题"}))

            self.assertEqual(
                json.loads(destination.read_text(encoding="utf-8")),
                {"title": "标题"},
            )


if __name__ == "__main__":
    unittest.main()
