#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "wechat-article-pipeline"
SCRIPTS = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS))

import doctor_wechat_article_skill as doctor  # noqa: E402
import platform_delivery_state as delivery  # noqa: E402


class ReleaseDoctorTest(unittest.TestCase):
    def test_release_metadata_is_valid_and_identical_install_is_clean(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            installed = Path(temp_dir) / "wechat-article-pipeline"
            shutil.copytree(SKILL_DIR, installed)

            report = doctor.inspect(SKILL_DIR, installed)

            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["version"], "1.7.1")
            self.assertTrue(report["installed"]["synced"])
            self.assertEqual(report["installed"]["missing"], [])
            self.assertEqual(report["installed"]["changed"], [])

    def test_release_doctor_reports_changed_install_without_reading_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            installed = Path(temp_dir) / "wechat-article-pipeline"
            shutil.copytree(SKILL_DIR, installed)
            (installed / "SKILL.md").write_text("changed", encoding="utf-8")
            (installed / ".env").write_text("SECRET=do-not-read", encoding="utf-8")

            report = doctor.inspect(SKILL_DIR, installed)

            self.assertFalse(report["installed"]["synced"])
            self.assertEqual(report["installed"]["changed"], ["SKILL.md"])
            serialized = json.dumps(report)
            self.assertNotIn("do-not-read", serialized)


class PlatformDeliveryStateTest(unittest.TestCase):
    def test_three_verified_results_complete_one_resumable_state(self) -> None:
        state = delivery.new_state("article", "标题")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for platform, payload in (
                ("wechat", {"status": "success", "mode": "draft"}),
                (
                    "toutiao",
                    {
                        "draft_verified": True,
                        "mode": "draft",
                        "expected_images": 3,
                        "verified_images": 3,
                        "expected_h1": 2,
                        "verified_h1": 2,
                        "clipboard_strategy": "native-selection-rich-html",
                    },
                ),
                (
                    "xiaohongshu",
                    {
                        "draft_verified": True,
                        "mode": "draft",
                        "expected_images": 3,
                        "verified_images": 3,
                        "expected_h1": 1,
                        "verified_h1": 1,
                        "expected_h2": 1,
                        "verified_h2": 1,
                        "clipboard_strategy": "native-selection-rich-html",
                    },
                ),
            ):
                result = root / f"{platform}.json"
                result.write_text(json.dumps(payload), encoding="utf-8")
                state = delivery.record_result(state, platform, payload, result)

        self.assertEqual(state["overall_status"], "verified")
        self.assertTrue(state["platforms"]["wechat"]["draft_verified"])
        self.assertEqual(state["platforms"]["xiaohongshu"]["verified"]["h2"], 1)

    def test_submission_maybe_sent_is_a_one_way_latch(self) -> None:
        state = delivery.new_state("article", "标题")
        result = Path("toutiao-result.json")
        state = delivery.record_result(
            state,
            "toutiao",
            {"submission_maybe_sent": True, "status": "unknown"},
            result,
        )
        state = delivery.record_result(
            state,
            "toutiao",
            {"submission_maybe_sent": False, "status": "failed"},
            result,
        )

        self.assertTrue(state["platforms"]["toutiao"]["submission_maybe_sent"])
        self.assertEqual(state["overall_status"], "partial_failure")


if __name__ == "__main__":
    unittest.main()
