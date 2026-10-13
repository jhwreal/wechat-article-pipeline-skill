from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "wechat-article-pipeline" / "scripts"))

import publish_wechat_api as publisher  # noqa: E402
import wechat_account_config as accounts  # noqa: E402


PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR42mNk+M/wHwAF/gL+IpcQ3wAAAABJRU5ErkJggg=="
)


class NamedAccountCredentialsTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manifest = self.root / "article.publish-manifest.json"
        self.out = self.root / "result.json"
        self.env_file = self.root / ".env"
        self.config = self.root / "legacy.json"
        self.cache = self.root / "token.json"
        self.manifest.write_text(json.dumps({
            "title": "标题", "author": "测试", "digest": "摘要",
            "content_html": "<p>正文。</p>", "cover": {"src": PNG},
        }), encoding="utf-8")
        self.config.write_text(json.dumps({
            "appid": "appid-A", "appsecret": "secret-A",
            "access_token_cache": {
                "appid": "appid-A", "access_token": "token-A",
                "expires_at": time.time() + 7200,
            },
        }), encoding="utf-8")
        self.api = mock.Mock(return_value={"access_token": "fresh-token", "expires_in": 7200})
        self.body = mock.Mock(side_effect=lambda html, token: (html, []))
        self.cover = mock.Mock(return_value={
            "thumb_media_id": "thumb-test", "width": 3, "height": 2,
        })
        self.draft = mock.Mock(return_value="draft-test")

    def set_env(self, named_fields: str = "", *, default_credentials: bool = True) -> None:
        default = "WECHAT_APPID=appid-A\nWECHAT_APPSECRET=secret-A\n" if default_credentials else ""
        self.env_file.write_text(default + "WECHAT_ACCOUNT_B_NAME=账号B\n" + named_fields, encoding="utf-8")

    def invoke(self, *extra_args: str) -> dict:
        argv = [
            "publish_wechat_api.py", str(self.manifest), "--create-draft",
            "--env-file", str(self.env_file), "--config", str(self.config),
            "--out", str(self.out), *extra_args,
        ]
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(sys, "argv", argv))
            stack.enter_context(mock.patch.object(publisher, "DEFAULT_TOKEN_CACHE", self.cache))
            stack.enter_context(mock.patch.object(publisher, "api_post_json", self.api))
            stack.enter_context(mock.patch.object(publisher, "upload_body_images", self.body))
            stack.enter_context(mock.patch.object(publisher, "upload_cover", self.cover))
            stack.enter_context(mock.patch.object(publisher, "create_draft", self.draft))
            stack.enter_context(mock.patch.object(publisher, "request_json", side_effect=AssertionError("unexpected network")))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            publisher.main()
        return json.loads(self.out.read_text(encoding="utf-8"))

    def assert_no_remote_work(self) -> None:
        self.api.assert_not_called()
        self.body.assert_not_called()
        self.cover.assert_not_called()
        self.draft.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_named_account_does_not_fill_missing_credentials_from_default_or_legacy(self) -> None:
        for fields in ("", "WECHAT_ACCOUNT_B_APPID=appid-B\n", "WECHAT_ACCOUNT_B_APPSECRET=secret-B\n"):
            with self.subTest(fields=fields):
                self.set_env(fields)
                with self.assertRaisesRegex(SystemExit, "Missing WeChat AppID/AppSecret"):
                    self.invoke("--account", "B")
                self.assert_no_remote_work()

    def test_cached_named_token_cannot_bypass_a_missing_secret(self) -> None:
        self.set_env("WECHAT_ACCOUNT_B_APPID=appid-B\n")
        cache = accounts.account_token_cache_path(self.cache, {"appid": "appid-B"})
        cache.write_text(json.dumps({
            "appid": "appid-B", "access_token": "cached-B", "expires_at": time.time() + 7200,
        }), encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "Missing WeChat AppID/AppSecret"):
            self.invoke("--account", "B")
        self.assert_no_remote_work()

    def test_complete_named_credentials_drive_token_cache_and_receipt(self) -> None:
        self.set_env("WECHAT_ACCOUNT_B_APPID=appid-B\nWECHAT_ACCOUNT_B_APPSECRET=secret-B\n")
        result = self.invoke("--account", "账号B", "--remember")
        self.api.assert_called_once_with("/cgi-bin/stable_token", {
            "grant_type": "client_credential", "appid": "appid-B", "secret": "secret-B",
        })
        self.assertEqual(result["account"]["alias"], "B")
        self.assertEqual(result["account"]["appid"], "appid-B")
        expected_cache = accounts.account_token_cache_path(self.cache, {"appid": "appid-B"})
        self.assertEqual(result["token_cache"], str(expected_cache))
        self.assertEqual(json.loads(expected_cache.read_text())["appid"], "appid-B")
        self.assertNotIn("secret-B", self.out.read_text())

    def test_complete_named_profile_can_reuse_its_matching_token(self) -> None:
        self.set_env("WECHAT_ACCOUNT_B_APPID=appid-B\nWECHAT_ACCOUNT_B_APPSECRET=secret-B\n")
        cache = accounts.account_token_cache_path(self.cache, {"appid": "appid-B"})
        cache.write_text(json.dumps({
            "appid": "appid-B", "access_token": "cached-B", "expires_at": time.time() + 7200,
        }), encoding="utf-8")
        self.invoke("--account", "B")
        self.api.assert_not_called()
        self.assertEqual(self.draft.call_args.args[1], "cached-B")

    def test_explicit_one_off_credentials_can_complete_a_named_profile(self) -> None:
        self.set_env()
        result = self.invoke("--account", "B", "--appid", "one-off", "--appsecret", "one-off-secret")
        self.api.assert_called_once_with("/cgi-bin/stable_token", {
            "grant_type": "client_credential", "appid": "one-off", "secret": "one-off-secret",
        })
        self.assertEqual(result["account"]["appid"], "one-off")
        self.assertEqual(result["token_cache"], str(accounts.account_token_cache_path(self.cache, {"appid": "one-off"})))

    def test_explicit_partial_override_does_not_enable_legacy_fallback_for_named_account(self) -> None:
        self.set_env()
        with self.assertRaisesRegex(SystemExit, "Missing WeChat AppID/AppSecret"):
            self.invoke("--account", "B", "--appid", "appid-B")
        self.assert_no_remote_work()

    def test_explicit_access_token_remains_a_one_off_override(self) -> None:
        self.set_env()
        result = self.invoke("--account", "B", "--access-token", "explicit-token")
        self.api.assert_not_called()
        self.assertEqual(self.draft.call_args.args[1], "explicit-token")
        self.assertEqual(result["account"]["appid"], "")

    def test_default_account_can_still_use_legacy_credentials_and_cache(self) -> None:
        self.set_env(default_credentials=False)
        result = self.invoke("--account", "default")
        self.api.assert_not_called()
        self.assertEqual(self.draft.call_args.args[1], "token-A")
        self.assertEqual(result["account"]["appid"], "appid-A")

    def test_default_account_can_still_fetch_with_legacy_credentials(self) -> None:
        self.set_env(default_credentials=False)
        result = self.invoke("--account", "default", "--force-refresh-token")
        self.api.assert_called_once_with("/cgi-bin/stable_token", {
            "grant_type": "client_credential", "appid": "appid-A", "secret": "secret-A", "force_refresh": True,
        })
        self.assertEqual(result["account"]["appid"], "appid-A")

    def test_resume_rejects_changed_appid_even_when_name_and_alias_match(self) -> None:
        self.set_env("WECHAT_ACCOUNT_B_APPID=appid-B\nWECHAT_ACCOUNT_B_APPSECRET=secret-B\n")
        self.invoke("--account", "B")
        self.set_env("WECHAT_ACCOUNT_B_APPID=appid-C\nWECHAT_ACCOUNT_B_APPSECRET=secret-C\n")
        self.api.reset_mock()
        self.draft.reset_mock()
        with self.assertRaisesRegex(SystemExit, "account appid changed"):
            self.invoke("--account", "B", "--resume")
        self.api.assert_not_called()
        self.draft.assert_not_called()

    def test_resume_keeps_compatibility_with_receipts_without_appid(self) -> None:
        self.set_env("WECHAT_ACCOUNT_B_APPID=appid-B\nWECHAT_ACCOUNT_B_APPSECRET=secret-B\n")
        result = self.invoke("--account", "B")
        del result["account"]["appid"]
        self.out.write_text(json.dumps(result), encoding="utf-8")
        self.api.reset_mock()
        self.draft.reset_mock()
        resumed = self.invoke("--account", "B", "--resume")
        self.assertEqual(resumed["status"], "success")
        self.api.assert_not_called()
        self.draft.assert_not_called()


if __name__ == "__main__":
    unittest.main()
