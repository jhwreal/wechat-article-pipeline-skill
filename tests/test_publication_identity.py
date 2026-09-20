from __future__ import annotations

import html
import json
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'wechat-article-pipeline/scripts'))
import article_identity as identity
import make_wechat_publish_manifest as manifest_builder
import platform_assets
import publish_wechat_api as publisher
import wechat_account_config as accounts


class PublicationIdentityTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_tokens_are_reused_only_for_the_resolved_appid(self):
        cache = self.root / 'token.json'
        args = SimpleNamespace(access_token=None, appid='B', appsecret='fake', token_cache=cache,
                               force_refresh_token=False, remember=True)
        for cached_appid in (None, 'A', 'B'):
            with self.subTest(cached_appid=cached_appid):
                cache.write_text(json.dumps({'appid': cached_appid, 'access_token': 'cached', 'expires_at': time.time()+7200}))
                with patch.object(publisher, 'api_post_json', return_value={'access_token':'fresh-B', 'expires_in':7200}) as api:
                    token = publisher.get_access_token(args, {}, {'appid': 'A'})
                self.assertEqual(token, 'cached' if cached_appid == 'B' else 'fresh-B')
                self.assertEqual(api.call_count, 0 if cached_appid == 'B' else 1)
                self.assertEqual(json.loads(cache.read_text())['appid'], 'B')
        self.assertNotEqual(accounts.account_token_cache_path(cache, {'appid':'A'}), accounts.account_token_cache_path(cache, {'appid':'B'}))

    def test_changed_or_reordered_images_invalidate_same_length_receipts(self):
        for name in ('a.png', 'b.png'):
            (self.root / name).write_bytes(name.encode())
        job = {'article_markdown': '# 标题\n\n![A](a.png)\n\n![B](b.png)', 'visuals': {}}
        path = self.root / 'article.job.json'
        receipt = platform_assets.platform_image_result_path(path)
        receipt.write_text(json.dumps({'status': 'success', 'source_fingerprint': identity.compute_source_fingerprint(job, self.root),
                                       'body_uploads':[{'url':'https://mmbiz.qpic.cn/a'}, {'url':'https://mmbiz.qpic.cn/b'}]}))
        self.assertEqual(len(platform_assets.discover_platform_image_urls(job, path)[0]), 2)
        reordered = {**job, 'article_markdown': '# 标题\n\n![B](b.png)\n\n![A](a.png)'}
        self.assertEqual(platform_assets.discover_platform_image_urls(reordered, path)[0], [])
        (self.root / 'a.png').write_bytes(b'replaced image at the same path')
        self.assertEqual(platform_assets.discover_platform_image_urls(job, path)[0], [])

    def test_legacy_or_unbound_explicit_hosted_urls_are_not_reused(self):
        job = {'article_markdown': '# 标题', 'platform_image_urls':['https://mmbiz.qpic.cn/old']}
        self.assertEqual(platform_assets.discover_platform_image_urls(job, self.root/'article.job.json')[0], [])
        job['platform_image_fingerprint'] = identity.compute_source_fingerprint(job, self.root)
        self.assertEqual(platform_assets.discover_platform_image_urls(job, self.root/'article.job.json')[0], job['platform_image_urls'])

    def test_publish_cli_rejects_stale_source_before_network_calls(self):
        job = {'article_markdown': '# 标题\n\n旧稿', 'visuals': {}}
        job_path = self.root / 'article.job.json'
        manifest = {'title':'标题', 'digest':'摘要', 'content_html':'<p>旧稿</p>',
                    'cover':{'src':'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR42mNk+M/wHwAF/gL+IpcQ3wAAAABJRU5ErkJggg=='},
                    'source_job': str(job_path), 'source_fingerprint': identity.compute_source_fingerprint(job, self.root)}
        job_path.write_text(json.dumps({**job, 'article_markdown':'# 标题\n\n新稿'}))
        manifest_path = self.root / 'manifest.json'; manifest_path.write_text(json.dumps(manifest))
        env = self.root / 'fake.env'; env.write_text('')
        for mode in ('--dry-run', '--create-draft'):
            argv = ['publisher', str(manifest_path), mode, '--env-file', str(env), '--config', str(self.root/'config.json')]
            with patch.object(sys, 'argv', argv), patch.object(publisher, 'get_access_token') as token:
                with self.assertRaisesRegex(SystemExit, 'stale'):
                    publisher.main()
                token.assert_not_called()

    def test_current_source_passes_but_pending_refresh_does_not(self):
        workbench = self.root/'article.html'; workbench.write_text('<html></html>')
        job = {'article_markdown':'# 标题', 'visuals':{}}
        workbench.with_suffix('.job.json').write_text(json.dumps(job))
        manifest = {'workbench_html':str(workbench), 'source_fingerprint':identity.compute_source_fingerprint(job, self.root)}
        identity.validate_source_freshness(manifest)
        support = self.root/'support'; support.mkdir()
        (support/'article.workbench-state.json').write_text(json.dumps({'coreRevision':1, 'manifest':{'state':'pending'}}))
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            identity.validate_source_freshness(manifest)

    def test_shared_markdown_cases_preserve_text_and_image_order(self):
        cases = json.loads((Path(__file__).parent/'fixtures/markdown-semantics.json').read_text())
        for case in cases:
            with self.subTest(name=case['name']):
                rendered = manifest_builder.markdown_to_wechat_html(case['markdown'])
                plain = html.unescape(re.sub(r'<[^>]+>', '', rendered))
                cursor = 0
                for fragment in case['text']:
                    at = plain.find(fragment, cursor)
                    self.assertGreaterEqual(at, 0, fragment)
                    cursor = at + len(fragment)
                positions = [rendered.index(name) for name in case.get('images', [])]
                self.assertEqual(positions, sorted(positions))
