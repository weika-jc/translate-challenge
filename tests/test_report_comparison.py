import csv
import tempfile
import unittest
from pathlib import Path

from report.analyze import load_models, summarize


OLD_FIELDS = [
    'dataset', 'src', 'tgt', 'raw', 'ref', 'trans', 'score', 'latency_ms',
]


def _write_old_csv(path: Path, rows: list[dict]) -> None:
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=OLD_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                'dataset': 'demo', 'src': 'en', 'tgt': 'fr',
                'ref': f"ref {row['raw']}", 'trans': '{"c":"ok"}',
                'latency_ms': '10', **row,
            })


class ReportComparisonTests(unittest.TestCase):
    def test_pairs_by_sample_identity_and_preserves_duplicate_occurrences(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_old_csv(root / 'a.csv', [
                {'raw': 'duplicate', 'score': '100'},
                {'raw': 'duplicate', 'score': '80'},
                {'raw': 'third', 'score': '70'},
                {'raw': 'tie', 'score': '60'},
                {'raw': 'unscored', 'score': ''},
                {'raw': 'a only', 'score': '50'},
            ])
            _write_old_csv(root / 'b.csv', [
                {'raw': 'third', 'score': '60'},
                {'raw': 'duplicate', 'score': '90'},
                {'raw': 'duplicate', 'score': '79'},
                {'raw': 'tie', 'score': '60'},
                {'raw': 'unscored', 'score': '50'},
                {'raw': 'b only', 'score': '50'},
            ])

            data = load_models([str(root / 'a.csv'), str(root / 'b.csv')])
            comparison = data['comparisons']['pairs'][0]

            self.assertEqual(comparison['common_count'], 5)
            self.assertEqual(comparison['score_paired_count'], 4)
            self.assertEqual(comparison['unscored_common_count'], 1)
            self.assertEqual(comparison['model_a_only_count'], 1)
            self.assertEqual(comparison['model_b_only_count'], 1)
            self.assertEqual(comparison['model_a_wins'], 3)
            self.assertEqual(comparison['ties'], 1)
            self.assertEqual(comparison['model_b_wins'], 0)
            self.assertEqual(comparison['mean_score_delta'], 5.25)
            self.assertEqual(comparison['conclusion'], 'model_a_better')
            self.assertEqual(comparison['winner'], 'a')
            self.assertGreater(comparison['ci95_low'], 0)
            self.assertEqual(comparison['by_dataset'][0]['paired_count'], 4)

    def test_structured_error_categories_are_summarized(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'new.csv'
            fields = [
                'dataset', 'src', 'tgt', 'raw', 'ref', 'trans_raw', 'trans',
                'translation_score', 'latency_ms', 'call_success', 'format_valid',
                'language_valid', 'policy_pass', 'judge_success', 'judge_acceptable',
                'judge_errors',
            ]
            with path.open('w', encoding='utf-8', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({
                    'dataset': 'demo', 'src': 'en', 'tgt': 'fr', 'raw': 'Hello',
                    'ref': 'Bonjour', 'trans_raw': '{"c":"Salut"}', 'trans': 'Salut',
                    'translation_score': '82', 'latency_ms': '10',
                    'call_success': 'True', 'format_valid': 'True',
                    'language_valid': 'True', 'policy_pass': 'True',
                    'judge_success': 'True', 'judge_acceptable': 'False',
                    'judge_errors': '[{"category":"accuracy","severity":"major"},'
                    '{"category":"fluency","severity":"minor"}]',
                })

            summary = summarize(load_models([str(path)])['models'][0]['records'])
            categories = {item['name']: item for item in summary['by_error_category']}
            self.assertEqual(categories['accuracy']['affected_records'], 1)
            self.assertEqual(categories['accuracy']['major'], 1)
            self.assertEqual(categories['fluency']['minor'], 1)
            self.assertEqual(categories['tone']['error_count'], 0)


if __name__ == '__main__':
    unittest.main()
