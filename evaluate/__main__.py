import asyncio
import csv
import json
import os
import sys
from pathlib import Path

from .protocol import (
    check_language,
    check_policy,
    parse_translation_output,
    policy_warning_errors,
    score_judge_errors,
)
from .utils import rate, translate

input_dir = 'output'
output_dir = 'result'
limit = 10
model_name = 'haiku-4-5-opt'
model_id = 'arn:aws:bedrock:us-west-2:686465264859:prompt/7ZJL56AKIU'  # test model
translation_structured_output = True
# model_name = 'gpt-oss-120b'
# model_id = 'arn:aws:bedrock:us-west-2:686465264859:prompt/1FWKA83D84'  # alter model

records = []
record_lock = asyncio.Lock()
CSV_FIELDS = [
    'dataset', 'src', 'tgt', 'raw', 'ref',
    'trans_raw', 'trans',
    'translation_structured',
    'call_success', 'call_error',
    'format_valid', 'format_error',
    'language_valid', 'language_check',
    'policy_pass', 'policy_violations', 'policy_warnings',
    'judge_success', 'judge_error', 'judge_raw', 'judge_acceptable',
    'judge_errors', 'judge_structured',
    'translation_score', 'score',
    'input_tokens', 'output_tokens', 'total_tokens', 'latency_ms',
    'judge_input_tokens', 'judge_output_tokens', 'judge_total_tokens', 'judge_latency_ms',
]

async def evaluate_file(dataset: str, data_path: str, ref_path: str, src: str, tgt: str):
    src_lines = Path(data_path).read_text(encoding='utf-8').splitlines()
    tgt_lines = Path(ref_path).read_text(encoding='utf-8').splitlines()
    processed = 0
    for raw, ref in zip(src_lines, tgt_lines):
        raw = raw.strip()
        ref = ref.strip()
        if not raw or not ref:
            continue
        call_error = None
        try:
            result = await translate(
                model_id,
                raw,
                tgt,
                structured=translation_structured_output,
            )
        except Exception as exc:
            result = None
            call_error = f'{type(exc).__name__}: {exc}'
            print(f'[debug] translate failed: {call_error}')

        trans_raw = result['text'] if result else None
        call_success = result is not None and trans_raw is not None
        if not call_success and call_error is None:
            call_error = 'response_does_not_contain_text'

        parsed = parse_translation_output(trans_raw) if call_success else None
        format_valid = parsed.valid if parsed else None
        format_error = parsed.error if parsed and not parsed.valid else None
        trans = parsed.text if parsed and parsed.valid else ''

        language = check_language(trans, tgt) if format_valid else None
        policy = check_policy(raw, trans, src, tgt, ref) if format_valid else None
        judge = await rate(raw, trans, tgt, ref) if format_valid else None
        scoring_errors = (
            [*judge['errors'], *policy_warning_errors(policy)]
            if judge and policy else None
        )
        translation_score = score_judge_errors(scoring_errors) if scoring_errors is not None else None

        record = {
            'dataset': dataset,
            'src': src,
            'tgt': tgt,
            'raw': raw,
            'ref': ref,
            'trans_raw': trans_raw,
            'trans': trans,
            'translation_structured': translation_structured_output,
            'call_success': call_success,
            'call_error': call_error,
            'format_valid': format_valid,
            'format_error': format_error,
            'language_valid': language.valid if language else None,
            'language_check': json.dumps({
                'reason': language.reason,
                'detected': language.detected,
                'confidence': language.confidence,
            }, ensure_ascii=False, separators=(',', ':')) if language else None,
            'policy_pass': policy.passed if policy else None,
            'policy_violations': json.dumps(
                policy.violations if policy else [], ensure_ascii=False, separators=(',', ':'),
            ) if policy else None,
            'policy_warnings': json.dumps(
                policy.warnings if policy else [], ensure_ascii=False, separators=(',', ':'),
            ) if policy else None,
            'judge_success': judge['success'] if judge else None,
            'judge_error': judge['error'] if judge else None,
            'judge_raw': judge['raw'] if judge else None,
            'judge_acceptable': judge['acceptable'] if judge else None,
            'judge_errors': json.dumps(
                judge['errors'] if judge else [], ensure_ascii=False, separators=(',', ':'),
            ) if judge else None,
            'judge_structured': judge['structured'] if judge else None,
            'translation_score': translation_score,
            # Temporary compatibility alias for the current report UI and old tooling.
            'score': translation_score,
            'input_tokens': result.get('input_tokens') if result else None,
            'output_tokens': result.get('output_tokens') if result else None,
            'total_tokens': result.get('total_tokens') if result else None,
            'latency_ms': result.get('latency_ms') if result else None,
            'judge_input_tokens': judge['input_tokens'] if judge else None,
            'judge_output_tokens': judge['output_tokens'] if judge else None,
            'judge_total_tokens': judge['total_tokens'] if judge else None,
            'judge_latency_ms': judge['latency_ms'] if judge else None,
        }
        async with record_lock:
            records.append(record)
        processed += 1
        if processed >= limit:
            break


async def evaluate_source(dataset: str, source_dir: str):
    files = os.listdir(source_dir)
    for file in files:
        if not file.endswith('.txt'):
            continue
        src, tgt = file.split('.')[:2]
        src_path = os.path.join(source_dir, file)
        tgt_path = os.path.join(source_dir, f'{tgt}.{src}.txt')
        if not os.path.exists(src_path) or not os.path.exists(tgt_path):
            continue
        await evaluate_file(dataset, src_path, tgt_path, src, tgt)


async def main():
    if not os.path.exists(input_dir):
        print(f'input directory {input_dir} does not exist')
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    datasets = os.listdir(input_dir)
    tasks = []
    for dataset in datasets:
        source_dir = os.path.join(input_dir, dataset)
        if not os.path.isdir(source_dir):
            continue
        tasks.append(asyncio.create_task(evaluate_source(dataset, source_dir)))

    await asyncio.gather(*tasks)

    csv_path = os.path.join(output_dir, f'{model_name}.csv')
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(records)


if __name__ == '__main__':
    asyncio.run(main())
