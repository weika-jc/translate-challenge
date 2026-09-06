import unittest

from report.pricing import calc_cost, get_pricing


class ReportPricingTests(unittest.TestCase):
    def test_luna_uses_us_geo_cache_read_pricing(self):
        pricing = get_pricing('gpt-5-6-luna')

        self.assertEqual(pricing.input_per_million, 0.22)
        self.assertEqual(pricing.output_per_million, 1.32)
        self.assertEqual(pricing.billing_mode, 'cached_prompt')
        self.assertEqual(pricing.cached_input_ratio, 0.10)
        self.assertAlmostEqual(
            calc_cost(2, 9, 1366, pricing),
            (2 * 0.22 + 1355 * 0.022 + 9 * 1.32) / 1_000_000,
        )


if __name__ == '__main__':
    unittest.main()
