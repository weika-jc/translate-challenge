import csv
import json
import math
import os
import statistics
from pathlib import Path

from evaluate.protocol import parse_translation_output


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


def load_csv(path: str) -> list[dict]:
    records = []
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
            records.append({
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
        result.append({
            'name': name,
            'count': len(items),
            'avg_score': _avg(scores),
            'median_score': _median(scores),
            'min_score': min(scores) if scores else None,
            'max_score': max(scores) if scores else None,
            'avg_latency_ms': _avg(latencies),
            'avg_tokens': _avg(tokens),
        })
    return sorted(result, key=lambda x: x['avg_score'] or 0, reverse=True)


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
    return {'models': models}
