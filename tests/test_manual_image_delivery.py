import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'wechat-article-pipeline/scripts'))
import make_wechat_publish_manifest as manifest
import publish_wechat_api as publisher

class ManualImagesTest(unittest.TestCase):
    def test_relative_gif_is_embedded_without_changing_bytes(self):
        import base64
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'files').mkdir(); (root/'image').mkdir()
            raw = base64.b64decode('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7')
            (root/'image/a.gif').write_bytes(raw)
            result = manifest.embed_local_markdown_images('![动画](../image/a.gif)', root/'files')
            self.assertIn('data:image/gif;base64,' + base64.b64encode(raw).decode(), result)
            manifest.validate_publish_image_sources(result, {})
    def test_remote_urls_remain_rejected(self):
        source = '![x](https://example.com/x.png)'
        self.assertEqual(manifest.embed_local_markdown_images(source, Path('.')), source)
        with self.assertRaises(SystemExit): manifest.validate_publish_image_sources(source, {})
    def test_gif_never_silently_becomes_jpeg(self):
        from unittest.mock import patch
        image = publisher.LocalImage(Path('/nonexistent.gif'), 'image/gif', 720, 405)
        with patch.object(publisher, 'normalize_body_image_with_sips') as fallback:
            with self.assertRaisesRegex(SystemExit, '未转换为静态图'):
                publisher.normalize_body_image(image)
            fallback.assert_not_called()
