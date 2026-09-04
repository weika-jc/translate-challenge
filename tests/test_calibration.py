import json
import tempfile
import unittest
from pathlib import Path

from evaluate.calibration import (
    _binary_agreement_metrics,
    _load_reference_exclusions,
    _repair_added_wrapper_quotes,
)


class CalibrationMetricTests(unittest.TestCase):
    def test_loads_reference_exclusions_next_to_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            labels = root / 'human-labels.csv'
            labels.touch()
            (root / 'reference-exclusions.json').write_text(json.dumps([
                {'candidate_id': 'abc', 'reason': 'bad reference'},
            ]), encoding='utf-8')
            self.assertEqual(
                _load_reference_exclusions(labels),
                {'abc': 'bad reference'},
            )

    def test_repairs_only_artificial_legacy_wrapper_quotes(self):
        self.assertEqual(
            _repair_added_wrapper_quotes('"Hola mundo"', 'Hello world'),
            ('Hola mundo', True),
        )
        self.assertEqual(
            _repair_added_wrapper_quotes('“Bonjour”', 'Hello'),
            ('Bonjour', True),
        )
        self.assertEqual(
            _repair_added_wrapper_quotes('"Hola mundo"', '"Hello world"'),
            ('"Hola mundo"', False),
        )

    def test_balanced_accuracy_exposes_all_acceptable_prediction(self):
        rows = [
            {'human_acceptable': True, 'prediction': True}
            for _ in range(14)
        ] + [
            {'human_acceptable': False, 'prediction': True}
            for _ in range(2)
        ]

        metrics = _binary_agreement_metrics(rows, 'prediction')

        self.assertEqual(metrics['acceptable_recall'], 100.0)
        self.assertEqual(metrics['unacceptable_recall'], 0.0)
        self.assertEqual(metrics['balanced_accuracy'], 50.0)

    def test_binary_metrics_handle_missing_class(self):
        metrics = _binary_agreement_metrics(
            [{'human_acceptable': True, 'prediction': True}],
            'prediction',
        )
        self.assertEqual(metrics['acceptable_recall'], 100.0)
        self.assertIsNone(metrics['unacceptable_recall'])
        self.assertEqual(metrics['balanced_accuracy'], 100.0)


if __name__ == '__main__':
    unittest.main()
