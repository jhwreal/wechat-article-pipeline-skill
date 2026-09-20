from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'wechat-article-pipeline/scripts'))
import platform_delivery_state as delivery
import package_wechat_article_bundle as packager
import publish_wechat_api as publisher


class DeliveryRevisionSafetyTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.markdown = self.root/'article.md'; self.markdown.write_text('# 标题\n\n原稿')
        self.state_path = self.root/'delivery.json'

    def command(self, *args):
        output = io.StringIO()
        with patch.object(sys, 'argv', ['state', *map(str, args)]), contextlib.redirect_stdout(output):
            delivery.main()
        return json.loads(output.getvalue())

    def test_new_body_starts_new_revision_and_retains_completed_history(self):
        state = self.command('init', self.state_path, '--slug', 'article', '--markdown', self.markdown)
        for item in state['platforms'].values(): item['status'] = 'verified'
        state['overall_status'] = 'verified'
        self.state_path.write_text(json.dumps(state))
        self.markdown.write_text('# 标题\n\n更新正文')
        self.assertEqual(self.command('summary', self.state_path)['overall_status'], 'stale')
        new = self.command('init', self.state_path, '--slug', 'article', '--markdown', self.markdown)
        self.assertEqual(new['overall_status'], 'pending')
        self.assertEqual(new['history'][0]['overall_status'], 'verified')
        self.assertNotEqual(new['article']['source_fingerprint'], state['article']['source_fingerprint'])

    def test_changed_image_at_same_path_is_a_new_delivery_revision(self):
        image = self.root/'a.png'; image.write_bytes(b'first')
        self.markdown.write_text('# 标题\n\n![图](a.png)')
        original = delivery.source_fingerprint(self.markdown)
        image.write_bytes(b'second')
        self.assertNotEqual(original, delivery.source_fingerprint(self.markdown))

    def test_unknown_submission_cannot_be_cleared_by_new_body(self):
        state = self.command('init', self.state_path, '--slug', 'article', '--markdown', self.markdown)
        state['platforms']['toutiao'].update(status='unknown', submission_maybe_sent=True)
        self.state_path.write_text(json.dumps(state))
        self.markdown.write_text('# 标题\n\n新稿')
        with self.assertRaisesRegex(SystemExit, 'unknown'):
            self.command('init', self.state_path, '--slug', 'article', '--markdown', self.markdown)
        self.assertEqual(json.loads(self.state_path.read_text()), state)

    def test_receipt_requires_current_source_and_matching_counts(self):
        state = delivery.new_state('article', '标题', self.markdown)
        payload = {'draft_verified': True, 'source_fingerprint':'wrong', 'expected_images':3, 'verified_images':1,
                   'expected_h1':1, 'verified_h1':1}
        with self.assertRaisesRegex(ValueError, 'revision'):
            delivery.record_result(state, 'toutiao', payload, self.root/'result.json')
        payload['source_fingerprint'] = state['article']['source_fingerprint']
        result = delivery.record_result(state, 'toutiao', payload, self.root/'result.json')
        self.assertEqual(result['platforms']['toutiao']['status'], 'failed')
        self.assertFalse(result['platforms']['toutiao']['draft_verified'])
        payload['verified_images'] = 3
        self.assertEqual(delivery.record_result(state, 'toutiao', payload, self.root/'result.json')['platforms']['toutiao']['status'], 'verified')
        self.assertEqual(delivery.result_status('wechat', {'status':'success'}), 'ready')

    def test_article_revision_reuses_its_own_issue_after_another_article(self):
        previous = {'issue':100, 'issue_env_key':'WECHAT_ORIGINAL_ISSUE', 'article_id':'article-A'}
        signature = packager.resolve_signature_metadata(self.root/'fake.env', {'original_issue':'102', 'signature_author':'作者'},
                                                       None, None, True, previous, 'article-A')
        self.assertEqual(signature['issue'], 100)
        self.assertEqual(signature['counter_policy'], 'reuse_previous')
        env = self.root/'fake.env'; env.write_text('WECHAT_ORIGINAL_ISSUE=102\n')
        publisher.validate_original_issue_preflight({'article_signature':signature}, env)
        self.assertEqual(env.read_text(), 'WECHAT_ORIGINAL_ISSUE=102\n')

    def test_missing_or_wrong_article_signature_cannot_guess_an_issue(self):
        for previous in (None, {'issue':100, 'issue_env_key':'WECHAT_ACCOUNT_B_ORIGINAL_ISSUE'},
                         {'issue':100, 'issue_env_key':'WECHAT_ORIGINAL_ISSUE', 'article_id':'another'}):
            with self.subTest(previous=previous), self.assertRaises(SystemExit):
                packager.resolve_signature_metadata(self.root/'fake.env', {'original_issue':'102'}, None, None, True, previous, 'article-A')
