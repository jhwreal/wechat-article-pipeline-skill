#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "wechat-article-pipeline" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import wechat_account_config as account_config  # noqa: E402


class WeChatAccountConfigTest(unittest.TestCase):
    def test_named_account_can_be_selected_by_display_name(self) -> None:
        env = {
            "WECHAT_ACCOUNT_JUZI_NAME": "橘子",
            "WECHAT_ACCOUNT_JUZI_APPID": "appid",
            "WECHAT_ACCOUNT_JUZI_APPSECRET": "secret",
            "WECHAT_ACCOUNT_JUZI_AUTHOR": "作者",
            "WECHAT_ACCOUNT_JUZI_SIGNATURE_AUTHOR": "签名",
            "WECHAT_ACCOUNT_JUZI_ORIGINAL_ISSUE": "9",
            "WECHAT_ACCOUNT_JUZI_PREVIEW_ACCOUNT": "preview",
        }

        profile = account_config.find_account_profile(env, "橘子", include_credentials=True)

        self.assertEqual(profile["alias"], "JUZI")
        self.assertEqual(profile["name"], "橘子")
        self.assertEqual(profile["appid"], "appid")
        self.assertEqual(profile["appsecret"], "secret")
        self.assertEqual(profile["author"], "作者")
        self.assertEqual(profile["signature_author"], "签名")
        self.assertEqual(profile["original_issue"], "9")
        self.assertEqual(profile["preview_account"], "preview")

    def test_multiple_named_credential_accounts_require_selector(self) -> None:
        env = {
            "WECHAT_ACCOUNT_A_NAME": "甲",
            "WECHAT_ACCOUNT_A_APPID": "appid-a",
            "WECHAT_ACCOUNT_B_NAME": "乙",
            "WECHAT_ACCOUNT_B_APPID": "appid-b",
        }

        with self.assertRaises(SystemExit):
            account_config.find_account_profile(env, None, include_credentials=True)


if __name__ == "__main__":
    unittest.main()
