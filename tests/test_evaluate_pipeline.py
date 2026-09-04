import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import evaluate.__main__ as pipeline
import evaluate.utils as evaluate_utils


class EvaluatePipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        pipeline.records.clear()

    async def test_parsed_candidate_is_sent_to_judge_and_statuses_are_recorded(self):
        translation_result = {
            'text': '{"c":"Bonjour 3 🎉"}',
            'input_tokens': 10,
            'output_tokens': 5,
            'total_tokens': 15,
            'latency_ms': 100,
        }
        judge_result = {
            'success': True,
            'acceptable': True,
            'errors': [{'category': 'fluency', 'severity': 'minor'}],
            'score': 97,
            'raw': '{"errors":[{"category":"fluency","severity":"minor"}]}',
            'error': None,
            'input_tokens': 20,
            'output_tokens': 8,
            'total_tokens': 28,
            'latency_ms': 200,
            'structured': True,
        }

        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / 'en.fr.txt'
            reference_path = Path(directory) / 'fr.en.txt'
            source_path.write_text('Hello 3 🎉\n', encoding='utf-8')
            reference_path.write_text('Bonjour 3 🎉\n', encoding='utf-8')
            with (
                patch.object(pipeline, 'translate', AsyncMock(return_value=translation_result)),
                patch.object(pipeline, 'rate', AsyncMock(return_value=judge_result)) as judge,
            ):
                await pipeline.evaluate_file(
                    'test', str(source_path), str(reference_path), 'en', 'fr',
                )

        judge.assert_awaited_once_with('Hello 3 🎉', 'Bonjour 3 🎉', 'fr', 'Bonjour 3 🎉')
        self.assertEqual(len(pipeline.records), 1)
        record = pipeline.records[0]
        self.assertEqual(record['trans_raw'], '{"c":"Bonjour 3 🎉"}')
        self.assertEqual(record['trans'], 'Bonjour 3 🎉')
        self.assertTrue(record['call_success'])
        self.assertTrue(record['format_valid'])
        self.assertTrue(record['policy_pass'])
        self.assertTrue(record['judge_success'])
        self.assertTrue(record['judge_acceptable'])
        self.assertEqual(record['translation_score'], 97)
        self.assertEqual(record['score'], 97)

    async def test_invalid_translation_format_is_not_judged(self):
        translation_result = {
            'text': 'Bonjour',
            'input_tokens': 10,
            'output_tokens': 5,
            'total_tokens': 15,
            'latency_ms': 100,
        }
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / 'en.fr.txt'
            reference_path = Path(directory) / 'fr.en.txt'
            source_path.write_text('Hello\n', encoding='utf-8')
            reference_path.write_text('Bonjour\n', encoding='utf-8')
            with (
                patch.object(pipeline, 'translate', AsyncMock(return_value=translation_result)),
                patch.object(pipeline, 'rate', AsyncMock()) as judge,
            ):
                await pipeline.evaluate_file(
                    'test', str(source_path), str(reference_path), 'en', 'fr',
                )

        judge.assert_not_awaited()
        record = pipeline.records[0]
        self.assertTrue(record['call_success'])
        self.assertFalse(record['format_valid'])
        self.assertEqual(record['format_error'], 'invalid_json')
        self.assertIsNone(record['translation_score'])

    async def test_translate_does_not_add_wrapper_quotes(self):
        response = {
            'output': {'message': {'content': [{'text': '{"c":"Hola"}'}]}},
            'usage': {},
        }
        converse = AsyncMock(return_value=response)
        with patch.object(evaluate_utils, '_converse', converse):
            await evaluate_utils.translate('prompt-arn', 'Hello', 'es')
        self.assertEqual(
            converse.await_args.kwargs['promptVariables']['input']['text'],
            'Hello -> es',
        )

    async def test_translate_preserves_quotes_present_in_source(self):
        response = {
            'output': {'message': {'content': [{'text': '{"c":"Hola"}'}]}},
            'usage': {},
        }
        converse = AsyncMock(return_value=response)
        with patch.object(evaluate_utils, '_converse', converse):
            await evaluate_utils.translate('prompt-arn', 'He said "hello".', 'es')
        self.assertEqual(
            converse.await_args.kwargs['promptVariables']['input']['text'],
            'He said "hello". -> es',
        )

    async def test_rate_derives_acceptability_from_major_or_critical_errors(self):
        response = {
            'text': '{"errors":[{"category":"accuracy","severity":"major"}]}',
            'input_tokens': 10,
            'output_tokens': 5,
            'total_tokens': 15,
            'latency_ms': 100,
            'structured': True,
        }
        with patch.object(evaluate_utils, 'invoke_generic_model', AsyncMock(return_value=response)):
            result = await evaluate_utils.rate('source', 'candidate', 'fr', 'reference')

        self.assertFalse(result['acceptable'])
        self.assertEqual(result['score'], 85)


if __name__ == '__main__':
    unittest.main()
