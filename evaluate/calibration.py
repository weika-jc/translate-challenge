from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import random
import re
from collections import Counter
from pathlib import Path

from .protocol import (
    ERROR_CATEGORIES,
    ERROR_SEVERITIES,
    check_language,
    check_policy,
    parse_translation_output,
    policy_warning_errors,
    score_judge_errors,
)


HUMAN_FIELDS = [
    'candidate_id', 'split', 'dataset', 'src', 'tgt',
    'source', 'reference', 'candidate',
    'acceptable', 'worst_severity', 'primary_category', 'note',
]
SEVERITY_RANK = {'none': 0, 'minor': 1, 'major': 2, 'critical': 3}
_WRAPPER_QUOTE_PAIRS = (("\"", "\""), ("'", "'"), ('“', '”'), ('「', '」'), ('『', '』'))


def _stable_id(*parts: str) -> str:
    payload = '\x1f'.join(parts).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()[:16]


def _load_reference_exclusions(label_path: Path) -> dict[str, str]:
    path = label_path.with_name('reference-exclusions.json')
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, list):
        raise ValueError(f'{path}: expected a JSON array')
    exclusions = {}
    for index, item in enumerate(data, 1):
        if not isinstance(item, dict) or not isinstance(item.get('candidate_id'), str):
            raise ValueError(f'{path}: item {index} must contain candidate_id')
        exclusions[item['candidate_id']] = str(item.get('reason', 'reference_mismatch'))
    return exclusions


def _has_wrapper_quotes(text: str) -> bool:
    value = text.strip()
    return any(
        len(value) >= 2 and value.startswith(left) and value.endswith(right)
        for left, right in _WRAPPER_QUOTE_PAIRS
    )


def _repair_added_wrapper_quotes(candidate: str, source: str) -> tuple[str, bool]:
    """Remove one wrapper layer introduced by the legacy quoted-input bug."""
    value = candidate.strip()
    if _has_wrapper_quotes(source):
        return candidate, False
    for left, right in _WRAPPER_QUOTE_PAIRS:
        if len(value) >= 2 and value.startswith(left) and value.endswith(right):
            return value[len(left):-len(right)], True
    return candidate, False


def _sampling_tier(item: dict) -> str:
    try:
        if int(float(item['legacy_score'])) < 70:
            return 'suspected_error'
    except (TypeError, ValueError):
        pass

    source = item['source'].strip()
    related_pair = frozenset((item['src'], item['tgt'])) in {
        frozenset(('da', 'no')),
        frozenset(('de', 'nl')),
    }
    short_text = len(source) <= 30 or len(source.split()) <= 5
    special_content = bool(re.search(r'\d|[{}%]|[\U0001F300-\U0001FAFF]|^[-\'\"]', source))
    if related_pair or short_text or special_content:
        return 'edge_case'
    return 'normal'


def _read_candidates(paths: list[Path], repair_wrapper_quotes: bool = False) -> dict[str, list[dict]]:
    by_model: dict[str, list[dict]] = {}
    for path in paths:
        model = path.stem
        with path.open(encoding='utf-8', newline='') as handle:
            for row in csv.DictReader(handle):
                if 'trans_raw' in row:
                    candidate = row.get('trans', '').strip()
                else:
                    parsed = parse_translation_output(row.get('trans'))
                    candidate = parsed.text if parsed.valid else ''
                if not candidate:
                    continue
                wrapper_repaired = False
                if repair_wrapper_quotes:
                    candidate, wrapper_repaired = _repair_added_wrapper_quotes(
                        candidate, row.get('raw', ''),
                    )
                by_model.setdefault(model, []).append({
                    'model': model,
                    'source_file': str(path),
                    'dataset': row.get('dataset', ''),
                    'src': row.get('src', ''),
                    'tgt': row.get('tgt', ''),
                    'source': row.get('raw', ''),
                    'reference': row.get('ref', ''),
                    'candidate': candidate,
                    'wrapper_repaired': wrapper_repaired,
                    'legacy_score': row.get('translation_score') or row.get('score', ''),
                })
    return by_model


def create_human_sample(
    paths: list[Path],
    output_dir: Path,
    size: int,
    seed: int,
    exclude_labels: Path | None = None,
    holdout_size: int | None = None,
    repair_wrapper_quotes: bool = False,
    stratified: bool = False,
) -> None:
    by_model = _read_candidates(paths, repair_wrapper_quotes=repair_wrapper_quotes)
    if not by_model:
        raise ValueError('no valid translation candidates found')

    excluded_sources = set()
    if exclude_labels is not None:
        with exclude_labels.open(encoding='utf-8', newline='') as handle:
            excluded_sources = {
                (row['dataset'], row['src'], row['tgt'], row['source'], row['reference'])
                for row in csv.DictReader(handle)
            }

    rng = random.Random(seed)
    for rows in by_model.values():
        rng.shuffle(rows)

    selected = []
    used_sources = set()
    models = sorted(by_model)
    model_counts = Counter()
    dataset_counts = Counter()
    target_counts = Counter()
    band_counts = Counter()

    def score_band(item: dict) -> str:
        try:
            score = int(item['legacy_score'])
        except (TypeError, ValueError):
            return 'unknown'
        if score < 70:
            return 'low'
        if score < 90:
            return 'mid'
        return 'high'

    tier_targets = None
    tier_counts = Counter()
    if stratified:
        tier_targets = {
            'normal': size // 2,
            'suspected_error': size * 3 // 10,
        }
        tier_targets['edge_case'] = size - sum(tier_targets.values())

    while len(selected) < size:
        desired_tier = None
        if tier_targets:
            remaining = [
                tier for tier, target in tier_targets.items()
                if tier_counts[tier] < target
            ]
            if remaining:
                desired_tier = max(
                    remaining,
                    key=lambda tier: tier_targets[tier] - tier_counts[tier],
                )

        available = []
        for model in models:
            for item in by_model[model]:
                source_key = (
                    item['dataset'], item['src'], item['tgt'],
                    item['source'], item['reference'],
                )
                if source_key in used_sources or source_key in excluded_sources:
                    continue
                if desired_tier and _sampling_tier(item) != desired_tier:
                    continue
                available.append((item, source_key))

        if not available and desired_tier:
            tier_targets.pop(desired_tier)
            continue
        if not available:
            break

        item, source_key = min(
            available,
            key=lambda pair: (
                model_counts[pair[0]['model']],
                dataset_counts[pair[0]['dataset']],
                target_counts[pair[0]['tgt']],
                band_counts[score_band(pair[0])],
            ),
        )
        used_sources.add(source_key)
        selected.append(item)
        model_counts[item['model']] += 1
        dataset_counts[item['dataset']] += 1
        target_counts[item['tgt']] += 1
        band_counts[score_band(item)] += 1
        tier_counts[_sampling_tier(item)] += 1

    if len(selected) < size:
        raise ValueError(f'only {len(selected)} unique candidates available; requested {size}')

    rng.shuffle(selected)
    output_dir.mkdir(parents=True, exist_ok=True)
    label_path = output_dir / 'human-labels.csv'
    map_path = output_dir / 'human-label-map.csv'
    label_rows = []
    map_rows = []
    prepared = []
    for item in selected:
        candidate_id = _stable_id(
            str(seed), item['model'], item['dataset'], item['src'], item['tgt'],
            item['source'], item['candidate'],
        )
        prepared.append((candidate_id, item))

    if holdout_size is None:
        holdout_ids = {
            candidate_id for candidate_id, _ in prepared
            if int(candidate_id[:8], 16) % 10 < 3
        }
    else:
        if holdout_size < 0 or holdout_size >= len(prepared):
            raise ValueError('holdout_size must be between 0 and size - 1')
        holdout_ids = {
            candidate_id for candidate_id, _ in sorted(
                prepared,
                key=lambda pair: _stable_id('holdout', pair[0]),
            )[:holdout_size]
        }

    for candidate_id, item in prepared:
        split = 'holdout' if candidate_id in holdout_ids else 'dev'
        label_rows.append({
            'candidate_id': candidate_id,
            'split': split,
            'dataset': item['dataset'],
            'src': item['src'],
            'tgt': item['tgt'],
            'source': item['source'],
            'reference': item['reference'],
            'candidate': item['candidate'],
            'acceptable': '',
            'worst_severity': '',
            'primary_category': '',
            'note': '',
        })
        map_rows.append({
            'candidate_id': candidate_id,
            'model': item['model'],
            'source_file': item['source_file'],
            'legacy_score': item['legacy_score'],
            'legacy_score_band': score_band(item),
            'sampling_tier': _sampling_tier(item),
            'wrapper_repaired': item['wrapper_repaired'],
        })

    with label_path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=HUMAN_FIELDS)
        writer.writeheader()
        writer.writerows(label_rows)
    with map_path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                'candidate_id', 'model', 'source_file', 'legacy_score',
                'legacy_score_band', 'sampling_tier', 'wrapper_repaired',
            ],
        )
        writer.writeheader()
        writer.writerows(map_rows)
    split_counts = Counter(row['split'] for row in label_rows)
    print(json.dumps({
        'labels': str(label_path),
        'mapping': str(map_path),
        'count': len(label_rows),
        'splits': split_counts,
        'models': Counter(item['model'] for item in selected),
        'score_bands': Counter(score_band(item) for item in selected),
        'sampling_tiers': Counter(_sampling_tier(item) for item in selected),
        'wrapper_repairs': sum(item['wrapper_repaired'] for item in selected),
        'excluded_sources': len(excluded_sources),
    }, ensure_ascii=False, default=dict, indent=2))


_NUMBER_RE = re.compile(r'\d+')
_PLACEHOLDER_RE = re.compile(r'\{\{[^{}]+\}\}|\{[^{}]+\}|\$\{[^{}]+\}|%(?:\d+\$)?[a-zA-Z]')
_EMOJI_RE = re.compile(r'[\U0001F1E6-\U0001F1FF\U0001F300-\U0001FAFF\u2600-\u27BF]')


def _replace_first_number(text: str) -> str | None:
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    replacement = str(int(match.group()) + 1)
    return text[:match.start()] + replacement + text[match.end():]


def _remove_chunk(text: str, target: str) -> str | None:
    if target == 'ja' and len(text) >= 8:
        return text[:max(2, len(text) // 2)]
    words = text.split()
    if len(words) < 4:
        return None
    return ' '.join(words[:max(1, len(words) // 2)])


def build_contrastive_cases(label_path: Path, output_path: Path) -> None:
    cases = []
    excluded_ids = set(_load_reference_exclusions(label_path))
    with label_path.open(encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            if row['candidate_id'] in excluded_ids:
                continue
            common = {
                'source': row['source'],
                'source_language': row['src'],
                'target_language': row['tgt'],
                'reference': row['reference'],
                'good_candidate': row['reference'],
            }
            if row['source'].strip().casefold() != row['reference'].strip().casefold():
                cases.append({
                    'case_id': f"{row['candidate_id']}-source-copy",
                    'corruption': 'source_copy',
                    **common,
                    'bad_candidate': row['source'],
                })

            corrupted = _replace_first_number(row['reference'])
            corruption = 'number_replacement'
            if corrupted is None:
                match = _PLACEHOLDER_RE.search(row['reference'])
                if match:
                    corrupted = row['reference'][:match.start()] + row['reference'][match.end():]
                    corruption = 'placeholder_deletion'
            if corrupted is None:
                match = _EMOJI_RE.search(row['reference'])
                if match:
                    corrupted = row['reference'][:match.start()] + row['reference'][match.end():]
                    corruption = 'emoji_deletion'
            if corrupted is None:
                corrupted = _remove_chunk(row['reference'], row['tgt'])
                corruption = 'content_deletion'
            if corrupted is not None and corrupted != row['reference']:
                cases.append({
                    'case_id': f"{row['candidate_id']}-{corruption}",
                    'corruption': corruption,
                    **common,
                    'bad_candidate': corrupted,
                })

    seed_path = label_path.with_name('contrastive-seeds.jsonl')
    if seed_path.exists():
        cases.extend(
            json.loads(line)
            for line in seed_path.read_text(encoding='utf-8').splitlines()
            if line.strip()
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', encoding='utf-8') as handle:
        for case in cases:
            handle.write(json.dumps(case, ensure_ascii=False) + '\n')
    print(json.dumps({
        'output': str(output_path),
        'count': len(cases),
        'by_corruption': Counter(case['corruption'] for case in cases),
    }, ensure_ascii=False, default=dict, indent=2))


def _model_label(model_id: str) -> str:
    for label in (
        'claude-haiku-4-5', 'claude-sonnet-4-6', 'gpt-oss-120b',
        'deepseek-v3-2', 'gemma-3-27b', 'glm-5', 'llama-4-maverick', 'nova-pro',
    ):
        if label in model_id:
            return label
    return model_id.rsplit('/', 1)[-1]


async def refresh_human_candidates(
    label_path: Path,
    map_path: Path,
    prompt_arn: str,
) -> None:
    from .utils import session, translate

    prompt_id = prompt_arn.rsplit('/', 1)[-1]
    region = prompt_arn.split(':')[3]
    prompt_client = session.client('bedrock-agent', region_name=region)
    prompt = await asyncio.to_thread(
        prompt_client.get_prompt,
        promptIdentifier=prompt_id,
        promptVersion='DRAFT',
    )
    default_variant = prompt.get('defaultVariant')
    variant = next(
        (item for item in prompt.get('variants', []) if item.get('name') == default_variant),
        None,
    )
    if variant is None or not variant.get('modelId'):
        raise ValueError('prompt Draft does not have a default variant model')
    actual_model_id = variant['modelId']

    with label_path.open(encoding='utf-8', newline='') as handle:
        rows = list(csv.DictReader(handle))

    mapping = []
    for index, row in enumerate(rows, 1):
        print(f"[calibration] refresh {index}/{len(rows)} {row['candidate_id']}")
        parsed = None
        result = None
        for _ in range(3):
            result = await translate(prompt_arn, row['source'], row['tgt'])
            parsed = parse_translation_output(result['text'] if result else None)
            if parsed.valid:
                break
        if parsed is None or not parsed.valid:
            raise RuntimeError(
                f"candidate {row['candidate_id']} failed format validation: "
                f"{parsed.error if parsed else 'no_response'}"
            )
        row['candidate'] = parsed.text
        for field in ('acceptable', 'worst_severity', 'primary_category', 'note'):
            row[field] = ''
        policy = check_policy(
            row['source'], parsed.text, row['src'], row['tgt'], row['reference'],
        )
        mapping.append({
            'candidate_id': row['candidate_id'],
            'model': _model_label(actual_model_id),
            'prompt_arn': 'managed-prompt',
            'actual_model_id': _model_label(actual_model_id),
            'translation_latency_ms': result['latency_ms'],
            'policy_pass': policy.passed,
            'policy_violations': json.dumps(
                policy.violations, ensure_ascii=False, separators=(',', ':'),
            ),
        })

    with label_path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=HUMAN_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    map_fields = [
        'candidate_id', 'model', 'prompt_arn', 'actual_model_id',
        'translation_latency_ms', 'policy_pass', 'policy_violations',
    ]
    with map_path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=map_fields)
        writer.writeheader()
        writer.writerows(mapping)
    print(json.dumps({
        'labels': str(label_path),
        'mapping': str(map_path),
        'count': len(rows),
        'prompt_arn': 'managed-prompt',
        'actual_model_id': _model_label(actual_model_id),
        'model': _model_label(actual_model_id),
        'policy_failures': sum(not item['policy_pass'] for item in mapping),
    }, ensure_ascii=False, indent=2))


def _worst_severity(errors: list[dict]) -> str:
    return max(
        (error['severity'] for error in errors),
        key=lambda value: SEVERITY_RANK[value],
        default='none',
    )


async def run_contrastive(
    input_path: Path,
    output_path: Path,
    limit: int | None,
    case_id_contains: str | None = None,
) -> None:
    from .utils import rate

    cases = [json.loads(line) for line in input_path.read_text(encoding='utf-8').splitlines() if line]
    if case_id_contains:
        cases = [case for case in cases if case_id_contains in case['case_id']]
    if limit is not None:
        cases = cases[:limit]
    rows = []
    for index, case in enumerate(cases, 1):
        print(f"[calibration] contrastive {index}/{len(cases)} {case['case_id']}")
        good = await rate(
            case['source'], case['good_candidate'], case['target_language'], case['reference'],
        )
        bad = await rate(
            case['source'], case['bad_candidate'], case['target_language'], case['reference'],
        )
        good_language = check_language(case['good_candidate'], case['target_language'])
        bad_language = check_language(case['bad_candidate'], case['target_language'])
        good_policy = check_policy(
            case['source'], case['good_candidate'],
            case.get('source_language', ''), case['target_language'], case['reference'],
        )
        bad_policy = check_policy(
            case['source'], case['bad_candidate'],
            case.get('source_language', ''), case['target_language'], case['reference'],
        )
        good_system_score = score_judge_errors([
            *good['errors'], *policy_warning_errors(good_policy),
        ]) if good['success'] else None
        bad_system_score = score_judge_errors([
            *bad['errors'], *policy_warning_errors(bad_policy),
        ]) if bad['success'] else None
        judge_passed = (
            good['success'] and bad['success']
            and good['score'] > bad['score']
        )
        good_hard_failures = int(good_language.valid is False) + int(not good_policy.passed)
        bad_hard_failures = int(bad_language.valid is False) + int(not bad_policy.passed)
        system_passed = (
            good['success'] and bad['success']
            and (-good_hard_failures, good_system_score)
            > (-bad_hard_failures, bad_system_score)
        )
        rows.append({
            'case_id': case['case_id'],
            'corruption': case['corruption'],
            'good_score': good['score'],
            'bad_score': bad['score'],
            'good_system_score': good_system_score,
            'bad_system_score': bad_system_score,
            'good_structured': good['structured'],
            'bad_structured': bad['structured'],
            'good_judge_latency_ms': good['latency_ms'],
            'bad_judge_latency_ms': bad['latency_ms'],
            'judge_passed': judge_passed,
            'system_passed': system_passed,
            'passed': system_passed,
            'good_language_valid': good_language.valid,
            'bad_language_valid': bad_language.valid,
            'good_policy_pass': good_policy.passed,
            'bad_policy_pass': bad_policy.passed,
            'good_policy_violations': json.dumps(
                good_policy.violations, ensure_ascii=False, separators=(',', ':'),
            ),
            'bad_policy_violations': json.dumps(
                bad_policy.violations, ensure_ascii=False, separators=(',', ':'),
            ),
            'good_policy_warnings': json.dumps(
                good_policy.warnings, ensure_ascii=False, separators=(',', ':'),
            ),
            'bad_policy_warnings': json.dumps(
                bad_policy.warnings, ensure_ascii=False, separators=(',', ':'),
            ),
            'good_errors': json.dumps(good['errors'], ensure_ascii=False, separators=(',', ':')),
            'bad_errors': json.dumps(bad['errors'], ensure_ascii=False, separators=(',', ':')),
            'error': good['error'] or bad['error'],
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)
    completed = [row for row in rows if not row['error']]
    judge_passed_count = sum(row['judge_passed'] for row in completed)
    system_passed_count = sum(row['system_passed'] for row in completed)
    print(json.dumps({
        'output': str(output_path),
        'attempted': len(rows),
        'completed': len(completed),
        'judge_passed': judge_passed_count,
        'judge_accuracy': round(
            judge_passed_count / len(completed) * 100, 2,
        ) if completed else None,
        'system_passed': system_passed_count,
        'system_accuracy': round(
            system_passed_count / len(completed) * 100, 2,
        ) if completed else None,
    }, ensure_ascii=False, indent=2))


def _validate_human_row(row: dict, line_number: int) -> None:
    if row['acceptable'] not in ('yes', 'no'):
        raise ValueError(f'line {line_number}: acceptable must be yes or no')
    if row['worst_severity'] not in ('none', *ERROR_SEVERITIES):
        raise ValueError(f'line {line_number}: invalid worst_severity')
    category = row['primary_category']
    if row['worst_severity'] == 'none' and category:
        raise ValueError(f'line {line_number}: primary_category must be blank when severity is none')
    if row['worst_severity'] != 'none' and category not in ERROR_CATEGORIES:
        raise ValueError(f'line {line_number}: invalid primary_category')


def _binary_agreement_metrics(rows: list[dict], prediction_field: str) -> dict[str, float | None]:
    acceptable = [row for row in rows if row['human_acceptable']]
    unacceptable = [row for row in rows if not row['human_acceptable']]
    acceptable_recall = (
        sum(row[prediction_field] is True for row in acceptable) / len(acceptable) * 100
        if acceptable else None
    )
    unacceptable_recall = (
        sum(row[prediction_field] is False for row in unacceptable) / len(unacceptable) * 100
        if unacceptable else None
    )
    recalls = [value for value in (acceptable_recall, unacceptable_recall) if value is not None]
    return {
        'acceptable_recall': round(acceptable_recall, 2) if acceptable_recall is not None else None,
        'unacceptable_recall': (
            round(unacceptable_recall, 2) if unacceptable_recall is not None else None
        ),
        'balanced_accuracy': round(sum(recalls) / len(recalls), 2) if recalls else None,
    }


async def run_human(label_path: Path, output_path: Path, split: str) -> None:
    from .utils import rate

    with label_path.open(encoding='utf-8', newline='') as handle:
        rows = list(csv.DictReader(handle))
    rows = [row for row in rows if split == 'all' or row['split'] == split]
    reference_exclusions = _load_reference_exclusions(label_path)
    excluded_count = sum(row['candidate_id'] in reference_exclusions for row in rows)
    rows = [row for row in rows if row['candidate_id'] not in reference_exclusions]
    for line_number, row in enumerate(rows, 2):
        _validate_human_row(row, line_number)

    results = []
    for index, row in enumerate(rows, 1):
        print(f"[calibration] human {index}/{len(rows)} {row['candidate_id']}")
        judge = await rate(row['source'], row['candidate'], row['tgt'], row['reference'])
        judge_severity = _worst_severity(judge['errors']) if judge['success'] else ''
        judge_acceptable = judge['acceptable'] if judge['success'] else None
        language = check_language(row['candidate'], row['tgt'])
        policy = check_policy(
            row['source'], row['candidate'], row['src'], row['tgt'], row['reference'],
        )
        system_score = score_judge_errors([
            *judge['errors'], *policy_warning_errors(policy),
        ]) if judge['success'] else None
        system_acceptable = (
            judge_acceptable and language.valid is not False and policy.passed
        ) if judge['success'] else None
        human_acceptable = row['acceptable'] == 'yes'
        human_severe = row['worst_severity'] in ('major', 'critical')
        ambiguous = 'ambiguous' in row.get('note', '').casefold()
        judge_severe = judge_severity in ('major', 'critical')
        system_severe = judge_severe or language.valid is False or not policy.passed
        results.append({
            'candidate_id': row['candidate_id'],
            'split': row['split'],
            'human_acceptable': human_acceptable,
            'ambiguous': ambiguous,
            'judge_acceptable': judge_acceptable,
            'system_acceptable': system_acceptable,
            'language_valid': language.valid,
            'policy_pass': policy.passed,
            'policy_violations': json.dumps(
                policy.violations, ensure_ascii=False, separators=(',', ':'),
            ),
            'policy_warnings': json.dumps(
                policy.warnings, ensure_ascii=False, separators=(',', ':'),
            ),
            'human_severity': row['worst_severity'],
            'judge_severity': judge_severity,
            'judge_score': judge['score'],
            'system_score': system_score,
            'judge_errors': json.dumps(judge['errors'], ensure_ascii=False, separators=(',', ':')),
            'judge_raw': judge['raw'],
            'judge_structured': judge['structured'],
            'judge_input_tokens': judge['input_tokens'],
            'judge_output_tokens': judge['output_tokens'],
            'judge_total_tokens': judge['total_tokens'],
            'judge_latency_ms': judge['latency_ms'],
            'judge_acceptable_agreement': (
                judge['success'] and human_acceptable == judge_acceptable
            ),
            'acceptable_agreement': judge['success'] and human_acceptable == system_acceptable,
            'severity_agreement': judge['success'] and row['worst_severity'] == judge_severity,
            'human_severe': human_severe,
            'severe_detected': judge['success'] and human_severe and system_severe,
            'primary_category_detected': (
                judge['success']
                and row['primary_category'] in {error['category'] for error in judge['errors']}
            ) if row['primary_category'] else None,
            'error': judge['error'],
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]) if results else [])
        if results:
            writer.writeheader()
            writer.writerows(results)
    completed = [row for row in results if not row['error']]
    core = [row for row in completed if not row['ambiguous']]
    severe = [row for row in core if row['human_severe']]
    categorized = [row for row in core if row['primary_category_detected'] is not None]
    judge_binary = _binary_agreement_metrics(core, 'judge_acceptable')
    system_binary = _binary_agreement_metrics(core, 'system_acceptable')
    print(json.dumps({
        'output': str(output_path),
        'split': split,
        'completed': len(completed),
        'reference_mismatch_excluded': excluded_count,
        'ambiguous_excluded': len(completed) - len(core),
        'core_evaluated': len(core),
        'acceptable_agreement': round(
            sum(row['acceptable_agreement'] for row in core) / len(core) * 100, 2,
        ) if core else None,
        'judge_only_acceptable_agreement': round(
            sum(row['judge_acceptable_agreement'] for row in core) / len(core) * 100, 2,
        ) if core else None,
        'severity_agreement': round(
            sum(row['severity_agreement'] for row in core) / len(core) * 100, 2,
        ) if core else None,
        'major_critical_recall': round(
            sum(row['severe_detected'] for row in severe) / len(severe) * 100, 2,
        ) if severe else None,
        'primary_category_recall': round(
            sum(row['primary_category_detected'] for row in categorized) / len(categorized) * 100, 2,
        ) if categorized else None,
        'judge_unacceptable_recall': judge_binary['unacceptable_recall'],
        'judge_balanced_accuracy': judge_binary['balanced_accuracy'],
        'system_unacceptable_recall': system_binary['unacceptable_recall'],
        'system_balanced_accuracy': system_binary['balanced_accuracy'],
    }, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description='LLM Judge calibration utilities')
    commands = parser.add_subparsers(dest='command', required=True)

    sample = commands.add_parser('sample', help='create an anonymous human calibration sample')
    sample.add_argument('csv', nargs='+', type=Path)
    sample.add_argument('--output-dir', type=Path, default=Path('calibration'))
    sample.add_argument('--size', type=int, default=50)
    sample.add_argument('--seed', type=int, default=20260903)
    sample.add_argument('--exclude-labels', type=Path)
    sample.add_argument('--holdout-size', type=int)
    sample.add_argument('--repair-wrapper-quotes', action='store_true')
    sample.add_argument('--stratified', action='store_true')

    contrastive = commands.add_parser('build-contrastive', help='create synthetic damaged pairs')
    contrastive.add_argument('--labels', type=Path, default=Path('calibration/human-labels.csv'))
    contrastive.add_argument('--output', type=Path, default=Path('calibration/contrastive.jsonl'))

    refresh = commands.add_parser('refresh-human', help='retranslate the human calibration candidates')
    refresh.add_argument('--labels', type=Path, default=Path('calibration/human-labels.csv'))
    refresh.add_argument('--mapping', type=Path, default=Path('calibration/human-label-map.csv'))
    refresh.add_argument('--prompt-arn', required=True)

    run_pairs = commands.add_parser('run-contrastive', help='judge synthetic damaged pairs')
    run_pairs.add_argument('--input', type=Path, default=Path('calibration/contrastive.jsonl'))
    run_pairs.add_argument('--output', type=Path, default=Path('calibration/contrastive-results.csv'))
    run_pairs.add_argument('--limit', type=int)
    run_pairs.add_argument('--case-id-contains')

    run_labels = commands.add_parser('run-human', help='measure Judge agreement with human labels')
    run_labels.add_argument('--labels', type=Path, default=Path('calibration/human-labels.csv'))
    run_labels.add_argument('--output', type=Path, default=Path('calibration/human-results.csv'))
    run_labels.add_argument('--split', choices=('dev', 'holdout', 'all'), default='dev')

    args = parser.parse_args()
    if args.command == 'sample':
        create_human_sample(
            args.csv, args.output_dir, args.size, args.seed,
            exclude_labels=args.exclude_labels,
            holdout_size=args.holdout_size,
            repair_wrapper_quotes=args.repair_wrapper_quotes,
            stratified=args.stratified,
        )
    elif args.command == 'build-contrastive':
        build_contrastive_cases(args.labels, args.output)
    elif args.command == 'refresh-human':
        asyncio.run(refresh_human_candidates(args.labels, args.mapping, args.prompt_arn))
    elif args.command == 'run-contrastive':
        asyncio.run(run_contrastive(
            args.input, args.output, args.limit, args.case_id_contains,
        ))
    elif args.command == 'run-human':
        asyncio.run(run_human(args.labels, args.output, args.split))


if __name__ == '__main__':
    main()
