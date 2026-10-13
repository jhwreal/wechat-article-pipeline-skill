from __future__ import annotations

import functools
import hashlib
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
import workbench_document as document_module
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

    def test_external_markdown_change_is_not_overwritten_by_an_open_workbench(self):
        html = self.article()
        doc = self.document(html)
        status = doc.status()
        external = '# 标题\n\n外部编辑器保存的新稿'
        html.with_suffix('.md').write_text(external)
        before = {path: path.read_bytes() for path in (html, html.with_suffix('.md'), html.with_suffix('.job.json'))}

        with self.assertRaises(server.RevisionConflict) as conflict:
            doc.save({'markdown': '# 标题\n\n浏览器旧稿修改', 'baseRevision': status['coreRevision'],
                      'baseFingerprint': status['contentFingerprint']})

        self.assertTrue(conflict.exception.current_status['sourceConflict'])
        self.assertEqual(conflict.exception.current_status['sourceConflictFiles'], ['article.md'])
        self.assertEqual(doc.status()['coreRevision'], 0)
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_external_source_change_stays_blocked_after_service_restart(self):
        for companion in ('.md', '.job.json'):
            with self.subTest(companion=companion):
                html = self.article(slug='restart-' + companion[1:].replace('.', '-'))
                first = self.document(html)
                first.close()
                path = html.with_suffix(companion)
                if companion == '.md':
                    path.write_text('# 标题\n\n外部新稿')
                else:
                    job = json.loads(path.read_text())
                    job['article_markdown'] = '# 标题\n\n外部新稿'
                    path.write_text(json.dumps(job))
                external = path.read_bytes()

                reopened = self.document(html)
                status = reopened.status()
                self.assertTrue(status['sourceConflict'])
                with self.assertRaises(server.RevisionConflict):
                    reopened.save({'markdown': '# 标题\n\n旧 HTML 内容',
                                   'baseRevision': status['coreRevision'], 'baseFingerprint': status['contentFingerprint']})
                self.assertEqual(path.read_bytes(), external)

    def test_full_external_rebuild_establishes_a_new_source_baseline(self):
        html = self.article()
        doc = self.document(html)
        old_status = doc.status()
        html.with_suffix('.md').write_text('# 标题\n\n外部新稿')
        self.assertTrue(doc.status()['sourceConflict'])
        self.article(markdown='# 标题\n\n外部新稿')
        self.assertFalse(doc.status()['sourceConflict'])
        with self.assertRaises(server.RevisionConflict):
            doc.save({'markdown': '# 标题\n\n旧稿', 'baseRevision': 0,
                      'baseFingerprint': old_status['contentFingerprint']})
        current = doc.status()
        result = doc.save({'markdown': '# 标题\n\n外部新稿继续编辑', 'baseRevision': current['coreRevision'],
                           'baseFingerprint': current['contentFingerprint']})
        self.assertTrue(result['saved'])
        self.assertFalse(doc.status()['sourceConflict'])

    def test_original_focused_and_image_rendered_sources_can_differ(self):
        html = self.article()
        image = self.root / 'cover.png'
        image.write_bytes(b'image')
        original = '# 标题\n\n原始正文。\n\n![题图]({{visual:cover}})\n'
        focused = original.replace('原始正文', '**原始正文**')
        rendered = focused.replace('{{visual:cover}}', 'cover.png')
        job = {'article_markdown': focused, 'visuals': {'cover': {'path': str(image)}}}
        html.write_text(builder.apply_template(job, builder.DEFAULT_TEMPLATE.read_text(), rendered))
        html.with_suffix('.md').write_text(original)
        html.with_suffix('.job.json').write_text(json.dumps(job))
        doc = self.document(html)
        self.assertFalse(doc.status()['sourceConflict'])

        edited = rendered.replace('正文', '正文更新')
        self.assertTrue(doc.save({'markdown': edited})['saved'])
        saved = html.with_suffix('.md').read_text()
        self.assertEqual(saved, edited.replace('cover.png', '{{visual:cover}}'))
        saved_job = json.loads(html.with_suffix('.job.json').read_text())
        self.assertEqual(saved_job['source_markdown']['sha256'], hashlib.sha256(saved.encode()).hexdigest())
        self.assertFalse(doc.status()['sourceConflict'])
        reopened = self.document(html)
        self.assertFalse(reopened.status()['sourceConflict'])
        self.assertTrue(reopened.save({'markdown': edited + '\n追加。'})['saved'])

    def test_packaged_source_snapshot_detects_changes_before_first_open(self):
        html = self.article()
        markdown_path = html.with_suffix('.md')
        job_path = html.with_suffix('.job.json')
        job = json.loads(job_path.read_text())
        job['source_markdown'] = {'path': str(markdown_path), 'sha256': hashlib.sha256(markdown_path.read_text().encode()).hexdigest()}
        job_path.write_text(json.dumps(job))
        markdown_path.write_text('# 标题\n\n打包后、首次打开前的修改')

        doc = self.document(html)
        self.assertTrue(doc.status()['sourceConflict'])
        with self.assertRaises(server.RevisionConflict):
            doc.save({'markdown': '# 标题\n\n旧稿'})

    def test_packaged_source_snapshot_accepts_original_crlf_bytes(self):
        html = self.article()
        markdown_path = html.with_suffix('.md')
        markdown_path.write_bytes('# 标题\r\n\r\n原文'.encode())
        job_path = html.with_suffix('.job.json')
        job = json.loads(job_path.read_text())
        job['source_markdown'] = {'path': str(markdown_path), 'sha256': hashlib.sha256(markdown_path.read_bytes()).hexdigest()}
        job_path.write_text(json.dumps(job))
        doc = self.document(html)
        self.assertFalse(doc.status()['sourceConflict'])
        self.assertTrue(doc.save({'markdown': '# 标题\n\n更新原文'})['saved'])

    def test_legacy_html_also_preserves_companion_changes(self):
        html = self.article()
        html.write_text('<script>const DEFAULT_MARKDOWN = `旧稿`;</script>')
        doc = self.document(html)
        html.with_suffix('.md').write_text('# 标题\n\n外部新稿')
        self.assertTrue(doc.status()['sourceConflict'])
        with self.assertRaises(server.RevisionConflict):
            doc.save({'markdown': '# 标题\n\n旧稿'})

    def test_transaction_recovery_updates_source_baseline_before_next_save(self):
        html = self.article()
        doc = self.document(html)
        original_replace = document_module.atomic_replace

        def fail_markdown_replace(source, target, **kwargs):
            if target == html.with_suffix('.md').resolve():
                raise OSError('simulated interrupted commit')
            return original_replace(source, target, **kwargs)

        with patch.object(document_module, 'atomic_replace', side_effect=fail_markdown_replace):
            with self.assertRaisesRegex(OSError, 'interrupted commit'):
                doc.save({'markdown': '# 标题\n\n事务恢复的新稿'})

        reopened = self.document(html)
        self.assertFalse(reopened.status().get('recovery_required', False))
        self.assertFalse(reopened.status()['sourceConflict'])
        self.assertEqual(reopened.status()['coreRevision'], 1)
        self.assertIn('事务恢复的新稿', html.with_suffix('.md').read_text())
        self.assertTrue(reopened.save({'markdown': '# 标题\n\n恢复后继续编辑', 'baseRevision': 1})['saved'])
        self.assertEqual(reopened.status()['coreRevision'], 2)

    def test_same_text_presentation_rebuild_accepts_the_updated_job(self):
        html = self.article()
        doc = self.document(html)
        job_path = html.with_suffix('.job.json')
        job = json.loads(job_path.read_text())
        job['article_signature'] = {'author': '作者', 'issue': '12'}
        job['theme_color'] = '#123456'
        job_path.write_text(json.dumps(job))
        self.assertTrue(doc.status()['sourceConflict'])
        html.write_text(builder.apply_template(job, builder.DEFAULT_TEMPLATE.read_text(), job['article_markdown']))

        self.assertFalse(doc.status()['sourceConflict'])
        self.assertTrue(doc.save({'markdown': '# 标题\n\n继续编辑', 'themeColor': '#123456'})['saved'])

    def test_same_text_rebuild_can_add_a_source_snapshot_to_a_legacy_package(self):
        html = self.article()
        doc = self.document(html)
        job_path = html.with_suffix('.job.json')
        job = json.loads(job_path.read_text())
        job['source_markdown'] = {
            'path': str(html.with_suffix('.md')),
            'sha256': hashlib.sha256(html.with_suffix('.md').read_text().encode()).hexdigest(),
        }
        job_path.write_text(json.dumps(job))
        self.assertTrue(doc.status()['sourceConflict'])
        html.write_text(builder.apply_template(job, builder.DEFAULT_TEMPLATE.read_text(), job['article_markdown']))
        self.assertFalse(doc.status()['sourceConflict'])
        self.assertTrue(doc.save({'markdown': job['article_markdown'] + '\n\n继续编辑。'})['saved'])

    def test_image_receipt_cannot_accept_a_changed_source_file(self):
        html = self.article()
        doc = self.document(html)
        html.with_suffix('.md').write_text('# 标题\n\n外部新稿')
        html.write_text(builder.replace_bootstrap(html.read_text(), {
            'platformImageUrls': ['https://mmbiz.qpic.cn/image'],
            'platformImageSource': '/tmp/receipt.json',
        }))

        self.assertTrue(doc.status()['sourceConflict'])
        with self.assertRaises(server.RevisionConflict):
            doc.save({'markdown': '# 标题\n\n旧稿修改'})

    def test_presentation_rebuild_needs_source_binding_to_accept_changed_markdown(self):
        for source_bound in (False, True):
            with self.subTest(source_bound=source_bound):
                html = self.article(slug=f'presentation-{source_bound}')
                doc = self.document(html)
                markdown_path = html.with_suffix('.md')
                markdown_path.write_text('# 标题\n\n原始稿单独变更')
                job_path = html.with_suffix('.job.json')
                job = json.loads(job_path.read_text())
                job['theme_color'] = '#123456'
                if source_bound:
                    job['source_markdown'] = {'path': str(markdown_path), 'sha256': hashlib.sha256(markdown_path.read_text().encode()).hexdigest()}
                job_path.write_text(json.dumps(job))
                html.write_text(builder.apply_template(job, builder.DEFAULT_TEMPLATE.read_text(), job['article_markdown']))
                self.assertEqual(doc.status()['sourceConflict'], not source_bound)

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
                saved = json.load(response)
                self.assertTrue(saved['saved'])
            self.assertIn('合法修改', a.with_suffix('.md').read_text())
            self.assertIn('B原文', b.with_suffix('.md').read_text())
            a.with_suffix('.md').write_text('# 标题\n\n外部新稿必须保留')
            payload.update(baseRevision=saved['revision'], baseFingerprint=saved['contentFingerprint'])
            with self.assertRaises(urllib.error.HTTPError) as conflict:
                opener.open(urllib.request.Request(origin + server.SAVE_ENDPOINT, json.dumps(payload).encode(), headers))
            self.assertEqual(conflict.exception.code, 409)
            self.assertTrue(json.load(conflict.exception)['sourceConflict'])
            self.assertIn('外部新稿必须保留', a.with_suffix('.md').read_text())
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join()
