import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from botocore.exceptions import ClientError

import evaluate.__main__ as pipeline
import evaluate.utils as evaluate_utils
from evaluate.protocol import TRANSLATION_OUTPUT_SCHEMA


class EvaluatePipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        pipeline.records.clear()

    def test_public_result_redacts_managed_prompt_arn(self):
        prompt_arn = f"arn:aws:bedrock:region:{'0' * 12}:prompt/example"
        self.assertEqual(
            pipeline._public_result_row({'model_id': prompt_arn})['model_id'],
            'managed-prompt',
        )

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
                patch.object(
                    pipeline, 'translate', AsyncMock(return_value=translation_result),
                ) as translator,
                patch.object(pipeline, 'rate', AsyncMock(return_value=judge_result)) as judge,
            ):
                await pipeline.evaluate_file(
                    'test', str(source_path), str(reference_path), 'en', 'fr',
                )

        translator.assert_awaited_once_with(
            pipeline.model_id,
            'Hello 3 🎉',
            'fr',
            structured=True,
        )
        judge.assert_awaited_once_with('Hello 3 🎉', 'Bonjour 3 🎉', 'fr', 'Bonjour 3 🎉')
        self.assertEqual(len(pipeline.records), 1)
        record = pipeline.records[0]
        self.assertEqual(record['trans_raw'], '{"c":"Bonjour 3 🎉"}')
        self.assertEqual(record['trans'], 'Bonjour 3 🎉')
        self.assertTrue(record['translation_structured'])
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

    async def test_failed_translation_preserves_attempt_metrics(self):
        sample = pipeline._sample(
            'test', 'test/en.fr.txt', 1, 0, 'en', 'fr', 'Hello', 'Bonjour',
        )
        failure = ClientError(
            {'Error': {'Code': 'ThrottlingException', 'Message': 'slow down'}},
            'Converse',
        )
        failure.evaluation_metrics = {
            'attempts': 3,
            'retries': 2,
            'first_call_success': False,
            'first_output_valid': None,
            'recovered_by_retry': False,
            'input_tokens': None,
            'output_tokens': None,
            'total_tokens': None,
            'latency_ms': 123,
        }
        with patch.object(pipeline, 'translate', AsyncMock(side_effect=failure)):
            record = await pipeline.translate_record(
                sample, 'test-model', 'prompt-arn', False,
            )

        self.assertFalse(record['call_success'])
        self.assertEqual(record['call_attempts'], 3)
        self.assertEqual(record['call_retries'], 2)
        self.assertFalse(record['first_call_success'])
        self.assertIsNone(record['first_output_valid'])
        self.assertFalse(record['recovered_by_retry'])
        self.assertEqual(record['latency_ms'], 123)

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
        self.assertNotIn('outputConfig', converse.await_args.kwargs)

    async def test_translate_uses_structured_output_when_enabled(self):
        response = {
            'output': {'message': {'content': [{'text': '{"c":"Hola"}'}]}},
            'usage': {},
        }
        converse = AsyncMock(return_value=response)
        with patch.object(evaluate_utils, '_converse', converse):
            result = await evaluate_utils.translate(
                'prompt-arn', 'Hello', 'es', structured=True,
            )

        json_schema = converse.await_args.kwargs['outputConfig']['textFormat'][
            'structure'
        ]['jsonSchema']
        self.assertEqual(json.loads(json_schema['schema']), TRANSLATION_OUTPUT_SCHEMA)
        self.assertEqual(json_schema['name'], 'translation_result')
        self.assertTrue(result['structured'])

    async def test_translate_does_not_fallback_when_structured_call_fails(self):
        converse = AsyncMock(side_effect=RuntimeError('structured output rejected'))
        with patch.object(evaluate_utils, '_converse', converse):
            with self.assertRaisesRegex(RuntimeError, 'structured output rejected'):
                await evaluate_utils.translate(
                    'prompt-arn', 'Hello', 'es', structured=True,
                )

        converse.assert_awaited_once()

    async def test_translate_retries_only_transient_service_errors(self):
        throttled = ClientError(
            {'Error': {'Code': 'ThrottlingException', 'Message': 'slow down'}},
            'Converse',
        )
        response = {
            'output': {'message': {'content': [{'text': '{"c":"Hola"}'}]}},
            'usage': {},
        }
        converse = AsyncMock(side_effect=[throttled, response])
        sleep = AsyncMock()
        with (
            patch.object(evaluate_utils, '_converse', converse),
            patch.object(evaluate_utils.asyncio, 'sleep', sleep),
            patch.object(evaluate_utils.random, 'uniform', return_value=0.25),
        ):
            result = await evaluate_utils.translate('prompt-arn', 'Hello', 'es')

        self.assertEqual(result['text'], '{"c":"Hola"}')
        self.assertEqual(converse.await_count, 2)
        sleep.assert_awaited_once_with(0.25)
        self.assertEqual(result['attempts'], 2)
        self.assertEqual(result['retries'], 1)
        self.assertFalse(result['first_call_success'])
        self.assertIsNone(result['first_output_valid'])
        self.assertTrue(result['recovered_by_retry'])

    async def test_translate_retries_unusable_output_and_accumulates_usage(self):
        malformed = {
            'output': {'message': {'content': [{'text': '```json\n{"c":"Hola"}\n```'}]}},
            'usage': {'inputTokens': 10, 'outputTokens': 5, 'totalTokens': 15},
        }
        valid = {
            'output': {'message': {'content': [{'text': '{"c":"Hola"}'}]}},
            'usage': {'inputTokens': 11, 'outputTokens': 4, 'totalTokens': 15},
        }
        converse = AsyncMock(side_effect=[malformed, valid])
        with (
            patch.object(evaluate_utils, '_converse', converse),
            patch.object(evaluate_utils.asyncio, 'sleep', AsyncMock()) as sleep,
            patch.object(evaluate_utils.random, 'uniform', return_value=0),
        ):
            result = await evaluate_utils.translate('prompt-arn', 'Hello', 'es')

        self.assertEqual(converse.await_count, 2)
        sleep.assert_awaited_once_with(0)
        self.assertEqual(result['attempts'], 2)
        self.assertEqual(result['retries'], 1)
        self.assertTrue(result['first_call_success'])
        self.assertFalse(result['first_output_valid'])
        self.assertTrue(result['final_output_valid'])
        self.assertTrue(result['recovered_by_retry'])
        self.assertEqual(result['input_tokens'], 21)
        self.assertEqual(result['output_tokens'], 9)
        self.assertEqual(result['total_tokens'], 30)

    async def test_translation_validation_error_is_not_retried(self):
        rejected = ClientError(
            {'Error': {'Code': 'ValidationException', 'Message': 'invalid outputConfig'}},
            'Converse',
        )
        converse = AsyncMock(side_effect=rejected)
        with (
            patch.object(evaluate_utils, '_converse', converse),
            patch.object(evaluate_utils.asyncio, 'sleep', AsyncMock()) as sleep,
        ):
            with self.assertRaises(ClientError):
                await evaluate_utils.translate(
                    'prompt-arn', 'Hello', 'es', structured=True,
                )

        converse.assert_awaited_once()
        sleep.assert_not_awaited()

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

    async def test_translate_sends_product_language_code(self):
        response = {
            'output': {'message': {'content': [{'text': '{"c":"Hei"}'}]}},
            'usage': {},
        }
        converse = AsyncMock(return_value=response)
        with patch.object(evaluate_utils, '_converse', converse):
            await evaluate_utils.translate('prompt-arn', 'Hello', 'no')

        self.assertEqual(
            converse.await_args.kwargs['promptVariables']['input']['text'],
            'Hello -> nb',
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

    async def test_rate_retries_invalid_json_output_and_recovers(self):
        malformed = {
            'output': {'message': {'content': [{'text': '```json\n{"errors":[]}\n```'}]}},
            'usage': {'inputTokens': 10, 'outputTokens': 5, 'totalTokens': 15},
        }
        valid = {
            'output': {'message': {'content': [{'text': '{"errors":[]}'}]}},
            'usage': {'inputTokens': 10, 'outputTokens': 3, 'totalTokens': 13},
        }
        converse = AsyncMock(side_effect=[malformed, valid])
        with (
            patch.object(evaluate_utils, '_converse', converse),
            patch.object(evaluate_utils.asyncio, 'sleep', AsyncMock()),
            patch.object(evaluate_utils.random, 'uniform', return_value=0),
        ):
            result = await evaluate_utils.rate('source', 'candidate', 'fr', 'reference')

        self.assertEqual(converse.await_count, 2)
        self.assertTrue(result['success'])
        self.assertEqual(result['attempts'], 2)
        self.assertTrue(result['first_call_success'])
        self.assertFalse(result['first_output_valid'])
        self.assertTrue(result['recovered_by_retry'])
        self.assertEqual(result['total_tokens'], 28)

    async def test_rate_reports_failure_after_invalid_output_retries_are_exhausted(self):
        malformed = {
            'output': {'message': {'content': [{'text': 'not-json'}]}},
            'usage': {'inputTokens': 10, 'outputTokens': 2, 'totalTokens': 12},
        }
        converse = AsyncMock(return_value=malformed)
        with (
            patch.object(evaluate_utils, '_converse', converse),
            patch.object(evaluate_utils.asyncio, 'sleep', AsyncMock()),
            patch.object(evaluate_utils.random, 'uniform', return_value=0),
        ):
            result = await evaluate_utils.rate('source', 'candidate', 'fr', 'reference')

        self.assertEqual(converse.await_count, 3)
        self.assertFalse(result['success'])
        self.assertEqual(result['attempts'], 3)
        self.assertEqual(result['retries'], 2)
        self.assertFalse(result['first_output_valid'])
        self.assertFalse(result['recovered_by_retry'])
        self.assertEqual(result['total_tokens'], 36)

    async def test_rate_sends_product_language_code_to_judge(self):
        response = {
            'text': '{"errors":[]}',
            'input_tokens': 10,
            'output_tokens': 5,
            'total_tokens': 15,
            'latency_ms': 100,
            'structured': True,
        }
        invoke = AsyncMock(return_value=response)
        with patch.object(evaluate_utils, 'invoke_generic_model', invoke):
            await evaluate_utils.rate('source', 'candidate', 'no', 'reference')

        judge_prompt = invoke.await_args.args[1]
        self.assertIn('"target_language": "nb"', judge_prompt)

    async def test_translation_stage_is_bounded_and_resumable(self):
        samples = [
            pipeline._sample(
                'test', 'test/en.fr.txt', index + 1, index,
                'en', 'fr', f'Hello {index}', f'Bonjour {index}',
            )
            for index in range(5)
        ]
        active = 0
        max_active = 0

        async def fake_translate(_model_id, text, _target, structured=False):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return {
                'text': json.dumps({'c': text.replace('Hello', 'Bonjour')}),
                'input_tokens': 1,
                'output_tokens': 1,
                'total_tokens': 2,
                'latency_ms': 10,
                'structured': structured,
            }

        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / 'translations.csv'
            with patch.object(pipeline, 'translate', AsyncMock(side_effect=fake_translate)) as call:
                first = await pipeline.run_translation_stage(
                    samples, checkpoint, 2, 'test-model', 'prompt-arn', True, True,
                )
            self.assertEqual(len(first), 5)
            self.assertEqual(call.await_count, 5)
            self.assertEqual(max_active, 2)

            with patch.object(pipeline, 'translate', AsyncMock()) as resumed_call:
                second = await pipeline.run_translation_stage(
                    samples, checkpoint, 2, 'test-model', 'prompt-arn', True, True,
                )
            resumed_call.assert_not_awaited()
            self.assertEqual([row['record_id'] for row in second], [
                sample['record_id'] for sample in samples
            ])

    async def test_discovery_converts_dataset_codes_to_product_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / 'test'
            dataset.mkdir()
            (dataset / 'en.no.txt').write_text('Hello\n', encoding='utf-8')
            (dataset / 'no.en.txt').write_text('Hei\n', encoding='utf-8')

            samples = pipeline.discover_samples(directory, per_file_limit=1)

        self.assertEqual(
            {(sample['src'], sample['tgt']) for sample in samples},
            {('en', 'nb'), ('nb', 'en')},
        )

    async def test_failed_judge_does_not_produce_a_quality_score(self):
        sample = pipeline._sample(
            'test', 'test/en.fr.txt', 1, 0, 'en', 'fr', 'Hello', 'Bonjour',
        )
        translation = {
            'text': '{"c":"Bonjour"}',
            'input_tokens': 1,
            'output_tokens': 1,
            'total_tokens': 2,
            'latency_ms': 10,
        }
        failed_judge = {
            'success': False,
            'acceptable': None,
            'errors': [],
            'score': None,
            'raw': None,
            'error': 'timeout',
            'input_tokens': None,
            'output_tokens': None,
            'total_tokens': None,
            'latency_ms': None,
            'structured': True,
        }
        with (
            patch.object(pipeline, 'translate', AsyncMock(return_value=translation)),
            patch.object(pipeline, 'rate', AsyncMock(return_value=failed_judge)),
        ):
            translated = await pipeline.translate_record(
                sample, 'test-model', 'prompt-arn', True,
            )
            judged = await pipeline.judge_record(translated)

        self.assertFalse(judged['judge_success'])
        self.assertIsNone(judged['translation_score'])
        self.assertIsNone(judged['score'])

    async def test_preflight_failure_stops_before_model_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / 'input' / 'test'
            dataset.mkdir(parents=True)
            (dataset / 'en.fr.txt').write_text('Hello\n', encoding='utf-8')
            (dataset / 'fr.en.txt').write_text('Bonjour\n', encoding='utf-8')
            args = SimpleNamespace(
                stage='translate',
                input_dir=str(root / 'input'),
                output_dir=str(root / 'result'),
                work_dir=str(root / 'work'),
                limit=1,
                model_name='test-model',
                model_id='prompt-arn',
                structured_output=True,
                translation_concurrency=2,
                judge_concurrency=2,
                resume=True,
            )
            with (
                patch.object(
                    pipeline,
                    'check_aws_identity',
                    AsyncMock(side_effect=RuntimeError('expired login')),
                ),
                patch.object(pipeline, 'translate', AsyncMock()) as translator,
            ):
                with self.assertRaisesRegex(RuntimeError, 'expired login'):
                    await pipeline.run(args)

        translator.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
