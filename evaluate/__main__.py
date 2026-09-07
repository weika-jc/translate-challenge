from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Awaitable, Callable

from .protocol import (
    canonical_language_code,
    check_language,
    check_policy,
    parse_translation_output,
    policy_warning_errors,
    score_judge_errors,
)
from .utils import check_aws_identity, rate, translate


input_dir = 'output'
output_dir = 'result'
work_dir = '.evaluation'
limit = 10
model_name = 'haiku-4-5-opt'
model_id = os.environ.get('BEDROCK_PROMPT_ARN', '')
translation_structured_output = True

records = []
record_lock = asyncio.Lock()
CSV_FIELDS = [
    'record_id', 'sample_index', 'model_name', 'model_id',
    'dataset', 'src', 'tgt', 'raw', 'ref',
    'trans_raw', 'trans',
    'translation_structured',
    'call_attempts', 'call_retries',
    'first_call_success', 'first_output_valid', 'recovered_by_retry',
    'call_success', 'call_error',
    'format_valid', 'format_error',
    'language_valid', 'language_check',
    'policy_pass', 'policy_violations', 'policy_warnings',
    'judge_success', 'judge_error', 'judge_raw', 'judge_acceptable',
    'judge_errors', 'judge_structured',
    'judge_attempts', 'judge_retries',
    'judge_first_call_success', 'judge_first_output_valid',
    'judge_recovered_by_retry',
    'translation_score', 'score',
    'input_tokens', 'output_tokens', 'total_tokens', 'latency_ms',
    'judge_input_tokens', 'judge_output_tokens', 'judge_total_tokens', 'judge_latency_ms',
]


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def _as_bool(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in ('True', 'true', '1', 1):
        return True
    if value in ('False', 'false', '0', 0):
        return False
    return None


def _stable_record_id(
    dataset: str,
    relative_path: str,
    line_number: int,
    src: str,
    tgt: str,
    raw: str,
    ref: str,
) -> str:
    payload = _json([
        dataset, relative_path, line_number, src, tgt, raw, ref,
    ]).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()[:20]


def _sample(
    dataset: str,
    relative_path: str,
    line_number: int,
    sample_index: int,
    src: str,
    tgt: str,
    raw: str,
    ref: str,
) -> dict:
    return {
        'record_id': _stable_record_id(
            dataset, relative_path, line_number, src, tgt, raw, ref,
        ),
        'sample_index': sample_index,
        'dataset': dataset,
        'src': src,
        'tgt': tgt,
        'raw': raw,
        'ref': ref,
    }


def discover_samples(source_root: str | Path, per_file_limit: int | None) -> list[dict]:
    root = Path(source_root)
    if not root.is_dir():
        raise FileNotFoundError(f'input directory {root} does not exist')
    if per_file_limit is not None and per_file_limit <= 0:
        raise ValueError('limit must be positive')

    samples = []
    for dataset_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        for source_path in sorted(dataset_dir.glob('*.txt')):
            parts = source_path.name.split('.')
            if len(parts) < 3:
                continue
            dataset_src, dataset_tgt = parts[:2]
            reference_path = dataset_dir / f'{dataset_tgt}.{dataset_src}.txt'
            if not reference_path.exists():
                continue
            src = canonical_language_code(dataset_src)
            tgt = canonical_language_code(dataset_tgt)
            source_lines = source_path.read_text(encoding='utf-8').splitlines()
            reference_lines = reference_path.read_text(encoding='utf-8').splitlines()
            processed = 0
            relative_path = str(source_path.relative_to(root))
            for line_number, (raw, ref) in enumerate(
                zip(source_lines, reference_lines), start=1,
            ):
                raw = raw.strip()
                ref = ref.strip()
                if not raw or not ref:
                    continue
                samples.append(_sample(
                    dataset_dir.name,
                    relative_path,
                    line_number,
                    len(samples),
                    src,
                    tgt,
                    raw,
                    ref,
                ))
                processed += 1
                if per_file_limit is not None and processed >= per_file_limit:
                    break
    return samples


async def translate_record(
    sample: dict,
    selected_model_name: str,
    selected_model_id: str,
    structured: bool,
) -> dict:
    call_error = None
    failure_metrics = {}
    try:
        result = await translate(
            selected_model_id,
            sample['raw'],
            sample['tgt'],
            structured=structured,
        )
    except Exception as exc:
        result = None
        failure_metrics = getattr(exc, 'evaluation_metrics', {})
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
    language = check_language(trans, sample['tgt']) if format_valid else None
    policy = check_policy(
        sample['raw'], trans, sample['src'], sample['tgt'], sample['ref'],
    ) if format_valid else None

    record = {field: None for field in CSV_FIELDS}
    metrics = result or failure_metrics
    attempts = metrics.get('attempts')
    if attempts is None and result is not None:
        # Keeps custom callers/tests compatible while production always returns
        # explicit attempt metadata.
        attempts = 1
    first_call_success = metrics.get('first_call_success')
    if first_call_success is None and attempts is not None:
        first_call_success = call_success
    first_output_valid = metrics.get('first_output_valid')
    if first_output_valid is None and attempts == 1 and call_success:
        first_output_valid = format_valid
    record.update({
        **sample,
        'model_name': selected_model_name,
        'model_id': selected_model_id,
        'trans_raw': trans_raw,
        'trans': trans,
        'translation_structured': structured,
        'call_attempts': attempts,
        'call_retries': metrics.get('retries', max(0, attempts - 1) if attempts else None),
        'first_call_success': first_call_success,
        'first_output_valid': first_output_valid,
        'recovered_by_retry': metrics.get('recovered_by_retry', False if attempts else None),
        'call_success': call_success,
        'call_error': call_error,
        'format_valid': format_valid,
        'format_error': format_error,
        'language_valid': language.valid if language else None,
        'language_check': _json({
            'reason': language.reason,
            'detected': language.detected,
            'confidence': language.confidence,
        }) if language else None,
        'policy_pass': policy.passed if policy else None,
        'policy_violations': _json(policy.violations) if policy else None,
        'policy_warnings': _json(policy.warnings) if policy else None,
        'input_tokens': metrics.get('input_tokens'),
        'output_tokens': metrics.get('output_tokens'),
        'total_tokens': metrics.get('total_tokens'),
        'latency_ms': metrics.get('latency_ms'),
    })
    return record


async def judge_record(record: dict) -> dict:
    record = dict(record)
    if _as_bool(record.get('format_valid')) is not True:
        return record

    policy = check_policy(
        record['raw'], record['trans'], record['src'], record['tgt'], record['ref'],
    )
    judge = await rate(record['raw'], record['trans'], record['tgt'], record['ref'])
    translation_score = None
    if judge['success']:
        scoring_errors = [*judge['errors'], *policy_warning_errors(policy)]
        translation_score = score_judge_errors(scoring_errors)

    record.update({
        'judge_success': judge['success'],
        'judge_error': judge['error'],
        'judge_raw': judge['raw'],
        'judge_acceptable': judge['acceptable'],
        'judge_errors': _json(judge['errors']),
        'judge_structured': judge['structured'],
        'judge_attempts': judge.get('attempts'),
        'judge_retries': judge.get('retries'),
        'judge_first_call_success': judge.get('first_call_success'),
        'judge_first_output_valid': judge.get('first_output_valid'),
        'judge_recovered_by_retry': judge.get('recovered_by_retry'),
        'translation_score': translation_score,
        # Temporary compatibility alias for the current report UI and old tooling.
        'score': translation_score,
        'judge_input_tokens': judge['input_tokens'],
        'judge_output_tokens': judge['output_tokens'],
        'judge_total_tokens': judge['total_tokens'],
        'judge_latency_ms': judge['latency_ms'],
    })
    return record


def _load_checkpoint(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(encoding='utf-8', newline='') as handle:
        rows = list(csv.DictReader(handle))
    if rows and 'record_id' not in rows[0]:
        raise ValueError(f'{path} is not a resumable checkpoint')
    return {row['record_id']: row for row in rows if row.get('record_id')}


def _validate_translation_checkpoint(
    rows: dict[str, dict],
    selected_model_name: str,
    selected_model_id: str,
    structured: bool,
) -> None:
    for row in rows.values():
        matches = (
            row.get('model_name') == selected_model_name
            and row.get('model_id') == selected_model_id
            and _as_bool(row.get('translation_structured')) is structured
        )
        if not matches:
            raise ValueError(
                'checkpoint configuration differs from this run; use --no-resume '
                'or choose another --work-dir'
            )


async def _run_checkpointed(
    items: list[dict],
    existing: dict[str, dict],
    checkpoint_path: Path,
    concurrency: int,
    worker: Callable[[dict], Awaitable[dict]],
    stage_name: str,
) -> dict[str, dict]:
    if concurrency <= 0:
        raise ValueError('concurrency must be positive')
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    missing = [item for item in items if item['record_id'] not in existing]
    if checkpoint_path.exists():
        with checkpoint_path.open(encoding='utf-8', newline='') as existing_handle:
            existing_fields = next(csv.reader(existing_handle), [])
        if existing_fields != CSV_FIELDS:
            # Schema additions should not corrupt an append-only checkpoint.
            # Historical rows remain resumable; their new observability fields
            # are intentionally blank because the first attempt is unknowable.
            _write_result(checkpoint_path, list(existing.values()))
    mode = 'a' if checkpoint_path.exists() else 'w'
    with checkpoint_path.open(mode, encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        if mode == 'w':
            writer.writeheader()
            handle.flush()

        queue = asyncio.Queue()
        for item in missing:
            queue.put_nowait(item)
        completed = 0

        async def consume() -> None:
            nonlocal completed
            while True:
                try:
                    item = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                result = await worker(item)
                existing[result['record_id']] = result
                writer.writerow({field: result.get(field) for field in CSV_FIELDS})
                handle.flush()
                completed += 1
                if completed % 25 == 0 or completed == len(missing):
                    print(f'[{stage_name}] {completed}/{len(missing)} new records complete')
                queue.task_done()

        workers = [
            asyncio.create_task(consume())
            for _ in range(min(concurrency, len(missing)))
        ]
        if workers:
            await asyncio.gather(*workers)
    return existing


def _ordered_rows(samples: list[dict], rows: dict[str, dict]) -> list[dict]:
    return [rows[sample['record_id']] for sample in samples if sample['record_id'] in rows]


def _public_result_row(row: dict) -> dict:
    public = dict(row)
    if ':prompt/' in str(public.get('model_id', '')):
        public['model_id'] = 'managed-prompt'
    return public


def _write_result(path: Path, rows: list[dict], redact_prompt_arn: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f'{path.suffix}.tmp')
    with temporary.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        output_rows = (_public_result_row(row) for row in rows) if redact_prompt_arn else rows
        writer.writerows({field: row.get(field) for field in CSV_FIELDS} for row in output_rows)
    os.replace(temporary, path)


async def run_translation_stage(
    samples: list[dict],
    checkpoint_path: Path,
    concurrency: int,
    selected_model_name: str,
    selected_model_id: str,
    structured: bool,
    resume: bool,
) -> list[dict]:
    if not resume and checkpoint_path.exists():
        checkpoint_path.unlink()
    existing = _load_checkpoint(checkpoint_path)
    _validate_translation_checkpoint(
        existing, selected_model_name, selected_model_id, structured,
    )

    async def worker(sample: dict) -> dict:
        return await translate_record(
            sample, selected_model_name, selected_model_id, structured,
        )

    completed = await _run_checkpointed(
        samples, existing, checkpoint_path, concurrency, worker, 'translate',
    )
    return _ordered_rows(samples, completed)


async def run_judge_stage(
    translated_rows: list[dict],
    checkpoint_path: Path,
    concurrency: int,
    resume: bool,
) -> list[dict]:
    if not resume and checkpoint_path.exists():
        checkpoint_path.unlink()
    existing = _load_checkpoint(checkpoint_path)
    completed = await _run_checkpointed(
        translated_rows, existing, checkpoint_path, concurrency, judge_record, 'judge',
    )
    return [
        completed[row['record_id']]
        for row in translated_rows
        if row['record_id'] in completed
    ]


async def evaluate_file(dataset: str, data_path: str, ref_path: str, src: str, tgt: str):
    """Compatibility helper for focused tests; the CLI uses the staged runner."""
    source_lines = Path(data_path).read_text(encoding='utf-8').splitlines()
    reference_lines = Path(ref_path).read_text(encoding='utf-8').splitlines()
    processed = 0
    for line_number, (raw, ref) in enumerate(zip(source_lines, reference_lines), start=1):
        raw = raw.strip()
        ref = ref.strip()
        if not raw or not ref:
            continue
        sample = _sample(
            dataset, Path(data_path).name, line_number, len(records), src, tgt, raw, ref,
        )
        record = await translate_record(
            sample, model_name, model_id, translation_structured_output,
        )
        record = await judge_record(record)
        async with record_lock:
            records.append(record)
        processed += 1
        if processed >= limit:
            break


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Run the staged translation evaluation')
    parser.add_argument('--stage', choices=('all', 'translate', 'judge'), default='all')
    parser.add_argument('--input-dir', default=input_dir)
    parser.add_argument('--output-dir', default=output_dir)
    parser.add_argument('--work-dir', default=work_dir)
    parser.add_argument('--limit', type=int, default=limit, help='records per language file')
    parser.add_argument('--model-name', default=model_name)
    parser.add_argument(
        '--model-id', default=model_id,
        help='managed Prompt ARN (defaults to BEDROCK_PROMPT_ARN)',
    )
    parser.add_argument(
        '--structured-output',
        action=argparse.BooleanOptionalAction,
        default=translation_structured_output,
    )
    parser.add_argument('--translation-concurrency', type=int, default=8)
    parser.add_argument('--judge-concurrency', type=int, default=8)
    parser.add_argument(
        '--resume', action=argparse.BooleanOptionalAction, default=True,
        help='reuse per-record checkpoints (default: enabled)',
    )
    args = parser.parse_args()
    if not args.model_id:
        parser.error('--model-id or BEDROCK_PROMPT_ARN is required')
    return args


async def run(args: argparse.Namespace) -> None:
    samples = discover_samples(args.input_dir, args.limit)
    state_dir = Path(args.work_dir) / args.model_name
    translation_path = state_dir / 'translations.csv'
    judge_path = state_dir / 'judged.csv'
    result_path = Path(args.output_dir) / f'{args.model_name}.csv'

    print(f'discovered {len(samples)} records')
    identity = await check_aws_identity()
    print(f"AWS identity: account={identity.get('Account')} arn={identity.get('Arn')}")

    if args.stage in ('all', 'translate'):
        if not args.resume and judge_path.exists():
            judge_path.unlink()
        translated_rows = await run_translation_stage(
            samples,
            translation_path,
            args.translation_concurrency,
            args.model_name,
            args.model_id,
            args.structured_output,
            args.resume,
        )
        print(f'translation checkpoint: {translation_path.resolve()}')
    else:
        translated = _load_checkpoint(translation_path)
        if not translated:
            raise FileNotFoundError(
                f'no translation checkpoint found at {translation_path}; run --stage translate first'
            )
        _validate_translation_checkpoint(
            translated, args.model_name, args.model_id, args.structured_output,
        )
        translated_rows = _ordered_rows(samples, translated)
        if len(translated_rows) != len(samples):
            raise RuntimeError(
                'translation checkpoint is incomplete; resume --stage translate first'
            )

    if args.stage in ('all', 'judge'):
        judged_rows = await run_judge_stage(
            translated_rows, judge_path, args.judge_concurrency, args.resume,
        )
        if len(judged_rows) != len(translated_rows):
            raise RuntimeError('judge stage ended before all translated rows were checkpointed')
        _write_result(result_path, judged_rows, redact_prompt_arn=True)
        print(f'evaluation result: {result_path.resolve()}')


def main() -> None:
    asyncio.run(run(_parse_args()))


if __name__ == '__main__':
    main()
