from __future__ import annotations

import functools
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'wechat-article-pipeline/scripts'
sys.path.insert(0, str(SCRIPTS))
import build_wechat_article_workbench as builder
import serve_wechat_workbench as server
import publish_wechat_api as publisher
from article_identity import compute_source_fingerprint


class WorkbenchRevisionSafetyTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def article(self, slug='article', markdown='# 标题\n\n原文'):
        html = self.root / f'{slug}.html'
        job = {'article_markdown': markdown, 'visuals': {}, 'storage_key': slug}
        html.write_text(builder.apply_template(job, builder.DEFAULT_TEMPLATE.read_text(), markdown))
        html.with_suffix('.job.json').write_text(json.dumps(job))
        html.with_suffix('.md').write_text(markdown)
        return html

    def document(self, html):
        document = server.WorkbenchDocument(html, self.root)
        self.addCleanup(document.close)
        return document

    def test_independent_documents_reject_obsolete_disk_revision(self):
        html = self.article()
        first, second = self.document(html), self.document(html)
        first.save({'markdown': '# 标题\n\n新稿', 'baseRevision': 0})
        with self.assertRaises(server.RevisionConflict):
            second.save({'markdown': '# 标题\n\n旧稿覆盖', 'baseRevision': 0})
        self.assertIn('新稿', html.with_suffix('.md').read_text())

    def test_external_rebuild_cannot_reuse_same_revision_with_different_content(self):
        html = self.article()
        doc = self.document(html)
        fingerprint = doc.status()['contentFingerprint']
        self.article(markdown='# 标题\n\n外部新稿')
        with self.assertRaises(server.RevisionConflict):
            doc.save({'markdown': '# 标题\n\n旧稿', 'baseRevision': 0, 'baseFingerprint': fingerprint})

    def test_receipt_updates_and_browser_saves_use_the_same_file_lock(self):
        html = self.article()
        doc = self.document(html)
        job = json.loads(html.with_suffix('.job.json').read_text())
        fingerprint = compute_source_fingerprint(job, self.root)
        manifest = {'workbench_html':str(html), 'source_fingerprint':fingerprint}
        result = {'status':'success', 'source_fingerprint':fingerprint, 'body_uploads':[{'url':'https://mmbiz.qpic.cn/a'}]}
        entered, release, saved = threading.Event(), threading.Event(), threading.Event()
        original = builder.replace_bootstrap
        outcomes = []
        def gated(source, updates):
            if 'platformImageUrls' in updates:
                entered.set()
                if not release.wait(5): raise RuntimeError('test gate timed out')
            return original(source, updates)
        def writer():
            outcomes.append(doc.save({'markdown':'# 标题\n\n并发保存的新稿', 'baseRevision':0}))
            saved.set()
        with patch.object(builder, 'replace_bootstrap', side_effect=gated):
            upload = threading.Thread(target=lambda: outcomes.append(publisher.sync_platform_images_to_workbench(manifest, result, self.root/'receipt.json')))
            upload.start()
            self.assertTrue(entered.wait(5))
            save = threading.Thread(target=writer); save.start()
            try:
                self.assertFalse(saved.wait(0.05))
            finally:
                release.set(); upload.join(5); save.join(5)
        self.assertTrue(saved.is_set())
        self.assertIn('并发保存的新稿', html.with_suffix('.md').read_text())
        self.assertEqual(len(outcomes), 2)

    def test_backslashes_and_html_characters_are_literal_titles(self):
        for title in (r'Windows C:\Users 路径', r'引用 \1 与 \g<1>', '<标题> & 内容'):
            with self.subTest(title=title):
                html = self.article(markdown=f'# {title}\n\n正文')
                doc = self.document(html)
                doc.save({'markdown': f'# {title}更新\n\n正文'})
                self.assertIn(title + '更新', builder.read_bootstrap(html.read_text())['markdown'])

    def test_http_binds_html_save_and_asset_requests_to_one_article(self):
        a, b = self.article('a'), self.article('b', '# B\n\nB原文')
        doc = self.document(a)
        httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(server.make_handler(doc), directory=str(self.root)))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            origin = f'http://127.0.0.1:{httpd.server_port}'
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with self.assertRaises(urllib.error.HTTPError) as blocked:
                opener.open(origin + '/b.html')
            self.assertEqual(blocked.exception.code, 404)
            with opener.open(origin + '/a.html') as response:
                bootstrap = builder.read_bootstrap(response.read().decode())
            with opener.open(origin + server.STATUS_ENDPOINT) as response:
                status = json.load(response)
            self.assertEqual(bootstrap['documentId'], status['documentId'])
            headers = {'Origin': origin, 'Content-Type': 'application/json', 'X-Workbench-Token': status['token']}
            payload = {'markdown': '# 标题\n\n合法修改', 'baseRevision': status['coreRevision'],
                       'baseFingerprint': status['contentFingerprint'], 'documentId': 'another-article'}
            with self.assertRaises(urllib.error.HTTPError) as blocked:
                opener.open(urllib.request.Request(origin + server.SAVE_ENDPOINT, json.dumps(payload).encode(), headers))
            self.assertEqual(blocked.exception.code, 400)
            payload['documentId'] = status['documentId']
            with opener.open(urllib.request.Request(origin + server.SAVE_ENDPOINT, json.dumps(payload).encode(), headers)) as response:
                self.assertTrue(json.load(response)['saved'])
            self.assertIn('合法修改', a.with_suffix('.md').read_text())
            self.assertIn('B原文', b.with_suffix('.md').read_text())
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join()
