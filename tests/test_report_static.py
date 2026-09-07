import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / 'report/static/app.js').read_text(encoding='utf-8')
INDEX_HTML = (ROOT / 'report/static/index.html').read_text(encoding='utf-8')


class ReportStaticTests(unittest.TestCase):
    def test_crowded_models_are_hidden_from_tabs_only(self):
        for model in (
            'gpt-5-6-luna-no-reasoning',
            'nova-pro',
            'deepseek-v3-2',
        ):
            with self.subTest(model=model):
                self.assertIn(f"'{model}'", APP_JS)
        self.assertIn(
            'state.data.models.filter(m => !HIDDEN_MODEL_TABS.has(m.name))',
            APP_JS,
        )
        self.assertIn('const rows = state.data.models.map(m => {', APP_JS)

    def test_model_comparison_has_sortable_cache_hit_column(self):
        self.assertIn('data-sort-key="cacheHit"', INDEX_HTML)
        self.assertIn('缓存命中 %', INDEX_HTML)
        self.assertIn('cacheHit: s.cache_hit_ratio', APP_JS)
        self.assertIn('${fmtPct(s.cache_hit_ratio)}</td>', APP_JS)


if __name__ == '__main__':
    unittest.main()
