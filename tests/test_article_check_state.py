import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'wechat-article-pipeline/scripts/article_check_state.py'
spec = importlib.util.spec_from_file_location('article_check_state', SCRIPT)
state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(state)


class CheckStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.article = Path(self.tmp.name) / 'article.md'
        self.article.write_text('# 标题\n\n正文')
        self.report = Path(self.tmp.name) / 'article.check.md'
        self.report.write_text('已通读全文，语法检查完成。')
        self.sha = state.digest(self.article)

    def record(self, scope='full'):
        return state.record(self.article, self.report, self.sha, scope)

    def test_missing_and_completed_idempotent(self):
        self.assertTrue(state.status(self.article)['needs_check'])
        self.assertFalse(self.record()['needs_check'])
        self.assertEqual(self.record()['check_count'], 1)

    def test_changed_article_requires_review(self):
        self.record()
        self.article.write_text('# 新标题\n\n新正文')
        result = state.status(self.article)
        self.assertEqual(result['check_count'], 1)
        self.assertEqual(result['current_check_count'], 0)
        with self.assertRaises(ValueError):
            self.record()

    def test_limited_scope_does_not_satisfy_language_review(self):
        self.assertTrue(self.record('other')['needs_check'])
        self.assertFalse(self.record('language')['needs_check'])

    def test_missing_or_changed_report_invalidates_evidence(self):
        self.record()
        self.report.write_text('被修改的报告')
        self.assertTrue(state.status(self.article)['needs_check'])
        self.report.unlink()
        self.assertTrue(state.status(self.article)['needs_check'])

    def test_other_article_cannot_reuse_state(self):
        self.record()
        other = self.article.with_name('other.md')
        other.write_bytes(self.article.read_bytes())
        self.assertTrue(state.status(other)['needs_check'])
        state.state_path(other).write_bytes(state.state_path(self.article).read_bytes())
        with self.assertRaises(ValueError):
            state.status(other)

    def test_corrupt_state_fails_closed(self):
        self.record()
        state.state_path(self.article).write_text('{bad json')
        with self.assertRaises(ValueError):
            state.status(self.article)


if __name__ == '__main__':
    unittest.main()
