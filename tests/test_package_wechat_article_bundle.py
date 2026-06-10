#!/usr/bin/env python3
from __future__ import annotations

import base64
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "wechat-article-pipeline" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import package_wechat_article_bundle as packager  # noqa: E402


PNG_1X1 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lpI1GQAAAABJRU5ErkJggg=="


class PackageWechatArticleBundleTest(unittest.TestCase):
    def test_image_size_reads_png_without_sips(self) -> None:
        original_run = packager.subprocess.run

        def unavailable_sips(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            raise FileNotFoundError("sips")

        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "one.png"
            image_path.write_bytes(base64.b64decode(PNG_1X1))
            packager.subprocess.run = unavailable_sips
            try:
                self.assertEqual(packager.image_size(image_path), (1, 1))
            finally:
                packager.subprocess.run = original_run


if __name__ == "__main__":
    unittest.main()
