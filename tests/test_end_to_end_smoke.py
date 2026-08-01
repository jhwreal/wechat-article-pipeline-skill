#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "wechat-article-pipeline" / "scripts"
POSTPROCESS = SCRIPTS / "postprocess_wechat_article.py"
PUBLISH = SCRIPTS / "publish_wechat_api.py"
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR42mNk+M/wHwAF/gL+IpcQ3wAAAABJRU5ErkJggg=="
)


class EndToEndSmokeTest(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, *args],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=90,
        )

    def test_full_image_package_manifest_and_api_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            files_dir = workspace / "files"
            images_dir = workspace / "image" / "smoke"
            files_dir.mkdir(parents=True)
            images_dir.mkdir(parents=True)
            article = files_dir / "smoke.md"
            out = files_dir / "smoke.html"
            image_jobs = files_dir / "smoke.image-jobs.json"
            env_file = workspace / ".env"
            result_file = files_dir / "smoke.wechat-api-result.json"
            article.write_text(
                "# 一次完整流水线冒烟测试\n\n"
                "![题图]({{visual:cover}})\n\n"
                "先从读者遇到的真实问题讲起，让文章有清楚的入口。\n\n"
                "![正文图]({{visual:body-1}})\n\n"
                "再给出一个能直接执行的方法，并解释为什么这样做有效。\n\n"
                "![尾图]({{visual:closing}})\n",
                encoding="utf-8",
            )
            env_file.write_text(
                "WECHAT_ACCOUNT_NAME=冒烟测试号\n"
                "WECHAT_AUTHOR=接口作者\n"
                "WECHAT_SIGNATURE_AUTHOR=署名作者\n"
                "WECHAT_ORIGINAL_ISSUE=1\n",
                encoding="utf-8",
            )

            common = (
                str(POSTPROCESS),
                str(article),
                str(out),
                "--workspace",
                str(workspace),
                "--article-slug",
                "smoke",
                "--jobs-out",
                str(image_jobs),
                "--no-focus-marking",
            )
            self.run_cli(*common, "--plan-only")
            planned = json.loads(image_jobs.read_text(encoding="utf-8"))
            self.assertEqual(planned["schema_version"], 2)
            self.assertEqual(len(planned["slots"]), 3)
            self.assertTrue(planned["rules"]["sha256"])
            for task in planned["generation_queue"]:
                (images_dir / task["output"]).write_bytes(PNG_1X1)

            self.run_cli(
                *common,
                "--publish-manifest",
                "--publisher-env-file",
                str(env_file),
                "--publisher-account",
                "default",
            )

            manifest = out.with_suffix(".publish-manifest.json")
            self.assertTrue(out.exists())
            self.assertTrue(out.with_suffix(".job.json").exists())
            self.assertTrue(manifest.exists())
            self.run_cli(
                str(PUBLISH),
                str(manifest),
                "--env-file",
                str(env_file),
                "--account",
                "default",
                "--out",
                str(result_file),
            )
            result = json.loads(result_file.read_text(encoding="utf-8"))
            self.assertTrue(result["dry_run"])
            self.assertEqual(result["validation"]["body_data_image_count"], 3)
            self.assertEqual(
                result["draft_payload_summary"]["thumb_media_id"],
                "DRY_RUN_THUMB_MEDIA_ID",
            )


if __name__ == "__main__":
    unittest.main()
