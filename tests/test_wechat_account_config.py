#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import stat
import subprocess
import sys
import tempfile
import time
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

    def test_issue_increment_is_idempotent_and_never_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_file = Path(tmp_dir) / ".env"
            env_file.write_text("UNRELATED=keep\nWECHAT_ORIGINAL_ISSUE=9\n", encoding="utf-8")
            env_file.chmod(0o640)

            result = account_config.compare_and_set_env_value(
                env_file,
                "WECHAT_ORIGINAL_ISSUE",
                "9",
                "10",
            )

            self.assertEqual(result, "updated")
            self.assertEqual(
                env_file.read_text(encoding="utf-8"),
                "UNRELATED=keep\nWECHAT_ORIGINAL_ISSUE=10\n",
            )
            self.assertEqual(stat.S_IMODE(env_file.stat().st_mode), 0o640)

            inode_after_update = env_file.stat().st_ino
            result = account_config.compare_and_set_env_value(
                env_file,
                "WECHAT_ORIGINAL_ISSUE",
                "9",
                "10",
            )
            self.assertEqual(result, "already_applied")
            self.assertEqual(env_file.stat().st_ino, inode_after_update)

            env_file.write_text("UNRELATED=keep\nWECHAT_ORIGINAL_ISSUE=11\n", encoding="utf-8")
            env_file.chmod(0o640)
            before_conflict = env_file.read_bytes()
            with self.assertRaisesRegex(ValueError, "conflict"):
                account_config.compare_and_set_env_value(
                    env_file,
                    "WECHAT_ORIGINAL_ISSUE",
                    "9",
                    "10",
                )
            self.assertEqual(env_file.read_bytes(), before_conflict)
            self.assertEqual(stat.S_IMODE(env_file.stat().st_mode), 0o640)

            windows_env = Path(tmp_dir) / "windows.env"
            windows_env.write_bytes(b"UNRELATED=keep\r\nWECHAT_ORIGINAL_ISSUE=9\r\n")
            account_config.compare_and_set_env_value(
                windows_env,
                "WECHAT_ORIGINAL_ISSUE",
                "9",
                "10",
            )
            self.assertEqual(
                windows_env.read_bytes(),
                b"UNRELATED=keep\r\nWECHAT_ORIGINAL_ISSUE=10\r\n",
            )

    def test_issue_increment_waits_for_sidecar_lock_and_rechecks_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            env_file = Path(tmp_dir) / ".env"
            env_file.write_text("WECHAT_ORIGINAL_ISSUE=9\n", encoding="utf-8")
            lock_path = account_config.env_lock_path(env_file)
            self.assertEqual(lock_path, env_file.with_name(env_file.name + ".lock"))
            lock_path.touch(mode=0o600)
            code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import wechat_account_config as account_config
try:
    account_config.compare_and_set_env_value(Path(sys.argv[2]), "WECHAT_ORIGINAL_ISSUE", "9", "10")
except ValueError:
    print("conflict")
    raise SystemExit(0)
raise SystemExit("compare-and-set unexpectedly overwrote the newer value")
"""

            with lock_path.open("a+b") as lock_handle:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                process = subprocess.Popen(
                    [sys.executable, "-c", code, str(SCRIPTS), str(env_file)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                try:
                    time.sleep(0.15)
                    self.assertIsNone(process.poll(), "compare-and-set did not wait for the sidecar lock")
                    env_file.write_text("WECHAT_ORIGINAL_ISSUE=11\n", encoding="utf-8")
                finally:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertIn("conflict", stdout)
            self.assertEqual(env_file.read_text(encoding="utf-8"), "WECHAT_ORIGINAL_ISSUE=11\n")


if __name__ == "__main__":
    unittest.main()
