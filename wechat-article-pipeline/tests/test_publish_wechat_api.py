from __future__ import annotations

import importlib.util
import json
import sys
import unittest
import urllib.request
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "publish_wechat_api.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("publish_wechat_api", SCRIPT)
assert spec and spec.loader
publish = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = publish
spec.loader.exec_module(publish)


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class RequestJsonTests(unittest.TestCase):
    def test_40164_is_an_immediate_explicit_whitelist_stop(self) -> None:
        response = _Response(
            {
                "errcode": 40164,
                "errmsg": "invalid ip 111.192.98.21 ipv6 ::ffff:111.192.98.21, not in whitelist",
            }
        )
        with mock.patch.object(urllib.request, "urlopen", return_value=response):
            with self.assertRaises(SystemExit) as raised:
                publish.request_json(urllib.request.Request("https://api.weixin.qq.com/test"))

        message = str(raised.exception)
        self.assertIn("WECHAT_IP_WHITELIST_BLOCKED", message)
        self.assertIn("发布流程已立即停止，未创建草稿", message)
        self.assertIn("当前出口 IP：111.192.98.21", message)
        self.assertIn("不要继续公众号上传或任何后续跨平台发布", message)


if __name__ == "__main__":
    unittest.main()
