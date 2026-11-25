from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "wechat-article-pipeline" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from check_xiaohongshu_handoff import check_images, check_submission
from platform_delivery_state import result_status


class XiaohongshuHandoffTest(unittest.TestCase):
    def test_hosted_images_are_counted_by_url_in_source_order(self):
        slots = ["cover", "body-1", "closing"]
        images = [{"slot": slot, "src": f"https://cdn.xhscdn.com/{slot}"} for slot in slots]
        result = check_images({"expected_slots": slots, "images": [images[0], *images]})
        self.assertTrue(result["ok"])
        self.assertEqual(result["verified_images"], 3)
        self.assertFalse(check_images({"expected_slots": slots, "images": images[::-1]})["ok"])
        partial = check_images({"expected_slots": slots, "images": [images[0], images[2]]})
        self.assertFalse(partial["ok"])
        self.assertEqual(partial["verified_images"], 2)
        self.assertEqual(partial["missing_slots"], ["body-1"])

    def test_empty_body_and_unhosted_or_misplaced_images(self):
        self.assertTrue(check_images({"expected_slots": [], "images": []})["ok"])
        for src in ("data:image/png,example", "https://cdn.xhscdn.com.invalid/image", ""):
            result = check_images({"expected_slots": ["cover"], "images": [{"slot": "cover", "src": src}]})
            self.assertFalse(result["ok"])
            self.assertEqual(result["verified_images"], 0)
        image = {"slot": "end", "src": "https://cdn.xhscdn.com/cover"}
        self.assertFalse(check_images({"expected_slots": ["cover"], "images": [image]})["ok"])

    def test_browser_draft_receipt_requires_reopening_before_aggregate_verification(self):
        receipt = {"ui_driver": "browser-subagent", "mode": "draft", "draft_verified": True,
                   "expected_images": 3, "verified_images": 3, "expected_h1": 1, "verified_h1": 1,
                   "expected_h2": 2, "verified_h2": 2}
        self.assertEqual(result_status("xiaohongshu", receipt), "failed")
        self.assertEqual(result_status("xiaohongshu", {**receipt, "draft_reopened": True}), "verified")
        self.assertEqual(result_status("xiaohongshu", {**receipt, "draft_reopened": True, "verified_images": 2}), "failed")

    def test_only_matching_public_mode_account_visibility_and_time_pass(self):
        target = {"mode": "schedule", "account": "测试号", "visibility": "公开", "beijing_time": "2027-01-02 07:30"}
        evidence = {"requested": target, "observed": dict(target), "submission_maybe_sent": False}
        self.assertTrue(check_submission(evidence)["ok"])
        for mismatch in ({"mode": "publish"}, {"account": "另一账号"}, {"visibility": "仅自己"},
                         {"beijing_time": "07:30"}, {"beijing_time": "2027-01-02 07:31"}):
            self.assertFalse(check_submission({**evidence, "observed": {**target, **mismatch}})["ok"])
        self.assertFalse(check_submission({**evidence, "submission_maybe_sent": True})["ok"])
        for mode, allowed in (("draft", False), ("test", False), ("publish", True)):
            settings = {"mode": mode, "account": "测试号", "visibility": "公开"}
            self.assertEqual(check_submission({**evidence, "requested": settings, "observed": settings})["ok"], allowed)

        del evidence["observed"]["beijing_time"]
        run = subprocess.run([sys.executable, str(SCRIPTS / "check_xiaohongshu_handoff.py"), "pre-submit", "-"],
                             input=json.dumps(evidence), text=True, capture_output=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertFalse(json.loads(run.stdout)["ok"])
