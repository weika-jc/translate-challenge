import csv
import hashlib
import json
import math
import os
import statistics
from collections import Counter
from itertools import combinations
from pathlib import Path

import numpy as np

from evaluate.protocol import ERROR_CATEGORIES, ERROR_SEVERITIES, parse_translation_output


BOOTSTRAP_ITERATIONS = 5_000
BOOTSTRAP_SEED = 20260904
SAMPLE_ID_FIELDS = ('dataset', 'src', 'tgt', 'raw', 'ref')


def validate_trans_json(text: str | None) -> tuple[bool, str]:
    """解析翻译结果 JSON；格式正确且含 \"c\" 字段视为有效。"""
    parsed = parse_translation_output(text)
    return parsed.valid, parsed.text


def parse_trans(text: str | None) -> str:
    valid, content = validate_trans_json(text)
    return content if valid else (str(text).strip() if text else '')


def _num(value, cast=float):
    if value is None or value == '':
        return None
    try:
        return cast(value)
    except (TypeError, ValueError):
        return None


def _is_empty(value) -> bool:
    return value is None or str(value).strip() == ''


def _bool(value) -> bool | None:
    if value is None or str(value).strip() == '':
        return None
    normalized = str(value).strip().lower()
    if normalized in ('true', '1', 'yes'):
        return True
    if normalized in ('false', '0', 'no'):
        return False
    return None


def _json(value, default):
    if _is_empty(value):
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def is_call_failed(raw_trans, raw_latency) -> bool:
    """模型输出或延迟为空视为调用失败。"""
    return _is_empty(raw_trans) or _is_empty(raw_latency)


def _sample_id(row: dict) -> str:
    """Stable identity shared by the same dataset row across model CSV files."""
    payload = json.dumps(
        [row.get(field, '') for field in SAMPLE_ID_FIELDS],
        ensure_ascii=False,
        separators=(',', ':'),
    ).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()[:16]


def load_csv(path: str) -> list[dict]:
    records = []
    occurrences: Counter[str] = Counter()
    with open(path, encoding='utf-8', newline='') as f:
        for row in csv.DictReader(f):
            score = _num(row.get('translation_score') or row.get('score'), int)
            raw_latency = row.get('latency_ms')
            is_new_protocol = 'trans_raw' in row
            if is_new_protocol:
                raw_trans = row.get('trans_raw')
                trans = row.get('trans', '')
                trans_valid = _bool(row.get('format_valid'))
                call_success = _bool(row.get('call_success'))
                call_failed = call_success is False
            else:
                raw_trans = row.get('trans')
                trans_valid, trans = validate_trans_json(raw_trans)
                call_failed = is_call_failed(raw_trans, raw_latency)
                call_success = not call_failed
            language_check = _json(row.get('language_check'), {})
            sample_id = _sample_id(row)
            sample_occurrence = occurrences[sample_id]
            occurrences[sample_id] += 1
            records.append({
                'sample_id': sample_id,
                'sample_occurrence': sample_occurrence,
                'dataset': row.get('dataset', ''),
                'src': row.get('src', ''),
                'tgt': row.get('tgt', ''),
                'lang_pair': f"{row.get('src', '')}→{row.get('tgt', '')}",
                'raw': row.get('raw', ''),
                'ref': row.get('ref', ''),
                'trans': trans,
                'trans_valid': trans_valid,
                'call_failed': call_failed,
                'call_success': call_success,
                'call_error': row.get('call_error', ''),
                'format_error': row.get('format_error', ''),
                'language_valid': _bool(row.get('language_valid')),
                'language_check': language_check,
                'language_attempted': bool(language_check),
                'policy_pass': _bool(row.get('policy_pass')),
                'policy_violations': _json(row.get('policy_violations'), []),
                'policy_warnings': _json(row.get('policy_warnings'), []),
                'judge_success': _bool(row.get('judge_success')),
                'judge_acceptable': _bool(row.get('judge_acceptable')),
                'judge_error': row.get('judge_error', ''),
                'judge_raw': row.get('judge_raw', ''),
                'judge_errors': _json(row.get('judge_errors'), []),
                'score': score,
                'input_tokens': _num(row.get('input_tokens'), int),
                'output_tokens': _num(row.get('output_tokens'), int),
                'total_tokens': _num(row.get('total_tokens'), int),
                'latency_ms': _num(row.get('latency_ms'), float),
                'judge_latency_ms': _num(row.get('judge_latency_ms'), float),
            })
    return records


def _avg(values: list) -> float | None:
    return round(statistics.mean(values), 2) if values else None


def _median(values: list) -> float | None:
    return round(statistics.median(values), 2) if values else None


def _p95(values: list) -> float | None:
    if not values:
        return None
    s = sorted(values)
    pos = 0.95 * (len(s) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return round(s[lo], 2)
    return round(s[lo] + (s[hi] - s[lo]) * (pos - lo), 2)


def _low_score_ratio(scores: list[int], threshold: int = 50) -> float | None:
    if not scores:
        return None
    low = sum(1 for s in scores if s < threshold)
    return round(low / len(scores) * 100, 2)


def _score_distribution(scores: list[int], step: int = 4) -> dict:
    labels = [f"{i}-{i + step - 1}" for i in range(0, 96, step)]
    labels.append("96-100")
    buckets = {label: 0 for label in labels}
    for s in scores:
        if s >= 96:
            buckets["96-100"] += 1
        else:
            start = (s // step) * step
            buckets[f"{start}-{start + step - 1}"] += 1
    return buckets


def _latency_distribution(latencies: list[float], step_ms: int = 1000) -> dict:
    if not latencies:
        return {}
    max_i = int(max(latencies) // step_ms)
    labels = [f"{i * step_ms}-{(i + 1) * step_ms - 1}" for i in range(max_i)]
    labels.append(f"≥{max_i * step_ms}")
    buckets = {label: 0 for label in labels}
    for lat in latencies:
        i = int(lat // step_ms)
        if i >= max_i:
            buckets[labels[-1]] += 1
        else:
            buckets[labels[i]] += 1
    return buckets


def _group_stats(records: list[dict], key: str) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for r in records:
        groups.setdefault(r[key], []).append(r)

    result = []
    for name, items in sorted(groups.items()):
        scores = [r['score'] for r in items if r['score'] is not None]
        latencies = [r['latency_ms'] for r in items if r['latency_ms'] is not None]
        tokens = [r['total_tokens'] for r in items if r['total_tokens'] is not None]
        language_checked = sum(1 for r in items if r['language_attempted'])
        policy_checked = sum(1 for r in items if r['policy_pass'] is not None)
        judge_checked = sum(1 for r in items if r['judge_success'] is not None)
        result.append({
            'name': name,
            'count': len(items),
            'scored_count': len(scores),
            'score_coverage': round(len(scores) / len(items) * 100, 2) if items else None,
            'avg_score': _avg(scores),
            'median_score': _median(scores),
            'min_score': min(scores) if scores else None,
            'max_score': max(scores) if scores else None,
            'avg_latency_ms': _avg(latencies),
            'avg_tokens': _avg(tokens),
            'call_failed_count': sum(1 for r in items if r['call_failed']),
            'malformed_count': sum(1 for r in items if r['trans_valid'] is False),
            'language_invalid_count': sum(1 for r in items if r['language_valid'] is False),
            'language_checked_count': language_checked,
            'policy_failed_count': sum(1 for r in items if r['policy_pass'] is False),
            'policy_checked_count': policy_checked,
            'judge_unacceptable_count': sum(
                1 for r in items
                if r['judge_success'] is True and r['judge_acceptable'] is False
            ),
            'judge_checked_count': judge_checked,
        })
    return sorted(result, key=lambda x: x['avg_score'] or 0, reverse=True)


def _error_category_stats(records: list[dict]) -> list[dict]:
    evaluated = [record for record in records if record['judge_success'] is True]
    if not evaluated:
        return []

    result = []
    for category in ERROR_CATEGORIES:
        affected = 0
        severities = Counter()
        for record in evaluated:
            matching = [
                error for error in record['judge_errors']
                if error.get('category') == category
            ]
            if matching:
                affected += 1
            severities.update(
                error.get('severity') for error in matching
                if error.get('severity') in ERROR_SEVERITIES
            )
        result.append({
            'name': category,
            'evaluated_count': len(evaluated),
            'affected_records': affected,
            'affected_ratio': round(affected / len(evaluated) * 100, 2),
            'error_count': sum(severities.values()),
            **{severity: severities[severity] for severity in ERROR_SEVERITIES},
        })
    return result


def summarize(records: list[dict]) -> dict:
    scores = [r['score'] for r in records if r['score'] is not None]
    latencies = [r['latency_ms'] for r in records if r['latency_ms'] is not None]
    input_tokens = [r['input_tokens'] for r in records if r['input_tokens'] is not None]
    output_tokens = [r['output_tokens'] for r in records if r['output_tokens'] is not None]
    total_tokens = [r['total_tokens'] for r in records if r['total_tokens'] is not None]
    malformed_count = sum(1 for r in records if r['trans_valid'] is False)
    valid_count = sum(1 for r in records if r['trans_valid'] is True)
    call_failed_count = sum(1 for r in records if r['call_failed'])
    call_success_count = len(records) - call_failed_count
    language_invalid_count = sum(1 for r in records if r['language_valid'] is False)
    language_unknown_count = sum(
        1 for r in records if r['language_attempted'] and r['language_valid'] is None
    )
    language_checked_count = sum(1 for r in records if r['language_attempted'])
    policy_failed_count = sum(1 for r in records if r['policy_pass'] is False)
    policy_warning_count = sum(len(r['policy_warnings']) for r in records)
    policy_checked_count = sum(1 for r in records if r['policy_pass'] is not None)
    judge_failed_count = sum(1 for r in records if r['judge_success'] is False)
    judge_attempted_count = sum(1 for r in records if r['judge_success'] is not None)

    return {
        'count': len(records),
        'valid_count': valid_count,
        'malformed_count': malformed_count,
        'malformed_ratio': round(malformed_count / call_success_count * 100, 2) if call_success_count else None,
        'call_failed_count': call_failed_count,
        'call_success_count': call_success_count,
        'call_failure_ratio': round(call_failed_count / len(records) * 100, 2) if records else None,
        'language_invalid_count': language_invalid_count,
        'language_unknown_count': language_unknown_count,
        'language_checked_count': language_checked_count,
        'language_invalid_ratio': round(
            language_invalid_count / language_checked_count * 100, 2,
        ) if language_checked_count else None,
        'policy_failed_count': policy_failed_count,
        'policy_checked_count': policy_checked_count,
        'policy_failure_ratio': round(
            policy_failed_count / policy_checked_count * 100, 2,
        ) if policy_checked_count else None,
        'policy_warning_count': policy_warning_count,
        'judge_failed_count': judge_failed_count,
        'judge_attempted_count': judge_attempted_count,
        'judge_failure_ratio': round(
            judge_failed_count / judge_attempted_count * 100, 2,
        ) if judge_attempted_count else None,
        'scored_count': len(scores),
        'avg_score': _avg(scores),
        'median_score': _median(scores),
        'min_score': min(scores) if scores else None,
        'max_score': max(scores) if scores else None,
        'std_score': round(statistics.stdev(scores), 2) if len(scores) > 1 else None,
        'avg_latency_ms': _avg(latencies),
        'median_latency_ms': _median(latencies),
        'p95_latency_ms': _p95(latencies),
        'low_score_ratio': _low_score_ratio(scores),
        'avg_input_tokens': _avg(input_tokens),
        'avg_output_tokens': _avg(output_tokens),
        'avg_total_tokens': _avg(total_tokens),
        'input_tokens_sum': sum(input_tokens) if input_tokens else None,
        'output_tokens_sum': sum(output_tokens) if output_tokens else None,
        'total_tokens_sum': sum(total_tokens) if total_tokens else None,
        'score_distribution': _score_distribution(scores),
        'latency_distribution': _latency_distribution(latencies),
        'by_dataset': _group_stats(records, 'dataset'),
        'by_lang_pair': _group_stats(records, 'lang_pair'),
        'by_src': _group_stats(records, 'src'),
        'by_tgt': _group_stats(records, 'tgt'),
        'by_error_category': _error_category_stats(records),
    }


def _percentile(values: np.ndarray, percentile: float) -> float:
    return float(np.percentile(values, percentile, method='linear'))


def paired_bootstrap_ci(
    differences: list[float],
    iterations: int = BOOTSTRAP_ITERATIONS,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float | None, float | None]:
    """Deterministic percentile bootstrap CI for the paired mean difference."""
    if not differences:
        return None, None
    if len(differences) == 1:
        value = round(float(differences[0]), 2)
        return value, value
    if iterations <= 0:
        raise ValueError('bootstrap iterations must be positive')

    values = np.asarray(differences, dtype=np.float64)
    rng = np.random.default_rng(seed)
    means = np.empty(iterations, dtype=np.float64)
    # Bound the temporary index matrix to roughly one million integers.
    chunk_size = max(1, min(iterations, 1_000_000 // len(values)))
    for start in range(0, iterations, chunk_size):
        stop = min(iterations, start + chunk_size)
        indices = rng.integers(
            0, len(values), size=(stop - start, len(values)), dtype=np.int32,
        )
        means[start:stop] = values[indices].mean(axis=1)
    return round(_percentile(means, 2.5), 2), round(_percentile(means, 97.5), 2)


def _paired_slice_stats(pairs: list[tuple[dict, dict]], key: str) -> list[dict]:
    groups: dict[str, list[tuple[dict, dict]]] = {}
    for left, right in pairs:
        groups.setdefault(left[key], []).append((left, right))

    result = []
    for name, items in groups.items():
        differences = [left['score'] - right['score'] for left, right in items]
        result.append({
            'name': name,
            'paired_count': len(items),
            'model_a_wins': sum(value > 0 for value in differences),
            'ties': sum(value == 0 for value in differences),
            'model_b_wins': sum(value < 0 for value in differences),
            'mean_score_delta': _avg(differences),
        })
    return sorted(result, key=lambda item: (-item['paired_count'], item['name']))


def _paired_error_stats(pairs: list[tuple[dict, dict]]) -> list[dict]:
    result = []
    for category in ERROR_CATEGORIES:
        left_evaluated = sum(left['judge_success'] is True for left, _ in pairs)
        right_evaluated = sum(right['judge_success'] is True for _, right in pairs)
        if not left_evaluated and not right_evaluated:
            continue

        def counts(index: int) -> tuple[int, int]:
            errors = [
                error
                for pair in pairs
                for error in pair[index]['judge_errors']
                if error.get('category') == category
            ]
            affected = sum(
                any(error.get('category') == category for error in pair[index]['judge_errors'])
                for pair in pairs
            )
            return affected, len(errors)

        left_affected, left_errors = counts(0)
        right_affected, right_errors = counts(1)
        result.append({
            'name': category,
            'model_a_evaluated': left_evaluated,
            'model_b_evaluated': right_evaluated,
            'model_a_affected': left_affected,
            'model_b_affected': right_affected,
            'model_a_errors': left_errors,
            'model_b_errors': right_errors,
        })
    return result


def compare_model_pair(model_a: dict, model_b: dict) -> dict:
    records_a = {
        (record['sample_id'], record['sample_occurrence']): record
        for record in model_a['records']
    }
    records_b = {
        (record['sample_id'], record['sample_occurrence']): record
        for record in model_b['records']
    }
    common_keys = sorted(records_a.keys() & records_b.keys())
    common_pairs = [(records_a[key], records_b[key]) for key in common_keys]
    scored_pairs = [
        pair for pair in common_pairs
        if pair[0]['score'] is not None and pair[1]['score'] is not None
    ]
    differences = [left['score'] - right['score'] for left, right in scored_pairs]
    seed_payload = f"{BOOTSTRAP_SEED}\0{model_a['name']}\0{model_b['name']}".encode('utf-8')
    pair_seed = int.from_bytes(hashlib.sha256(seed_payload).digest()[:8], 'big')
    ci_low, ci_high = paired_bootstrap_ci(differences, seed=pair_seed)
    if ci_low is not None and ci_low > 0:
        conclusion = 'model_a_better'
        winner = model_a['name']
    elif ci_high is not None and ci_high < 0:
        conclusion = 'model_b_better'
        winner = model_b['name']
    else:
        conclusion = 'uncertain'
        winner = None

    return {
        'model_a': model_a['name'],
        'model_b': model_b['name'],
        'common_count': len(common_pairs),
        'score_paired_count': len(scored_pairs),
        'score_coverage': round(len(scored_pairs) / len(common_pairs) * 100, 2)
        if common_pairs else None,
        'model_a_only_count': len(records_a.keys() - records_b.keys()),
        'model_b_only_count': len(records_b.keys() - records_a.keys()),
        'unscored_common_count': len(common_pairs) - len(scored_pairs),
        'model_a_wins': sum(value > 0 for value in differences),
        'ties': sum(value == 0 for value in differences),
        'model_b_wins': sum(value < 0 for value in differences),
        'model_a_avg_score': _avg([left['score'] for left, _ in scored_pairs]),
        'model_b_avg_score': _avg([right['score'] for _, right in scored_pairs]),
        'mean_score_delta': _avg(differences),
        'median_score_delta': _median(differences),
        'ci95_low': ci_low,
        'ci95_high': ci_high,
        'conclusion': conclusion,
        'winner': winner,
        'by_dataset': _paired_slice_stats(scored_pairs, 'dataset'),
        'by_lang_pair': _paired_slice_stats(scored_pairs, 'lang_pair'),
        'by_error_category': _paired_error_stats(common_pairs),
    }


def compare_models(models: list[dict]) -> dict:
    pairs = [compare_model_pair(left, right) for left, right in combinations(models, 2)]
    return {
        'methodology': {
            'score': 'model_a - model_b',
            'win_rule': 'higher_score',
            'confidence_interval': 'paired_percentile_bootstrap_95',
            'bootstrap_iterations': BOOTSTRAP_ITERATIONS,
            'bootstrap_seed': BOOTSTRAP_SEED,
            'pairing_fields': list(SAMPLE_ID_FIELDS),
            'missing_score_policy': 'exclude_from_score_comparison_and_report_coverage',
        },
        'pairs': pairs,
    }


def load_models(csv_paths: list[str]) -> dict:
    models = []
    for path in csv_paths:
        path = os.path.abspath(path)
        name = Path(path).stem
        records = load_csv(path)
        models.append({
            'name': name,
            'path': path,
            'summary': summarize(records),
            'records': records,
        })
    return {'models': models, 'comparisons': compare_models(models)}
