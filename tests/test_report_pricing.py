import unittest

from report.pricing import calc_cost, get_pricing


class ReportPricingTests(unittest.TestCase):
    def test_haiku_prompt_variants_share_pricing(self):
        self.assertEqual(
            get_pricing('haiku-4-5-opt-cache'),
            get_pricing('haiku-4-5'),
        )

    def test_luna_uses_us_geo_cache_read_pricing(self):
        pricing = get_pricing('gpt-5-6-luna')

        self.assertEqual(pricing.input_per_million, 0.22)
        self.assertEqual(pricing.output_per_million, 1.32)
        self.assertEqual(pricing.billing_mode, 'cached_prompt')
        self.assertEqual(pricing.cached_input_ratio, 0.10)
        self.assertEqual(pricing.cache_write_input_ratio, 1.25)
        self.assertAlmostEqual(pricing.cache_read_per_million, 0.022)
        self.assertAlmostEqual(pricing.cache_write_per_million, 0.275)
        self.assertAlmostEqual(
            calc_cost(2, 9, 1366, pricing, 1355, 0),
            (2 * 0.22 + 1355 * 0.022 + 9 * 1.32) / 1_000_000,
        )

    def test_luna_cache_write_uses_write_price(self):
        pricing = get_pricing('gpt-5-6-luna')

        self.assertAlmostEqual(
            calc_cost(2, 9, 1366, pricing, 0, 1355),
            (2 * 0.22 + 1355 * 0.275 + 9 * 1.32) / 1_000_000,
        )

    def test_old_csv_keeps_cache_read_estimate(self):
        pricing = get_pricing('gpt-5-6-luna')

        self.assertAlmostEqual(
            calc_cost(2, 9, 1366, pricing),
            (2 * 0.22 + 1355 * 0.022 + 9 * 1.32) / 1_000_000,
        )


if __name__ == '__main__':
    unittest.main()
