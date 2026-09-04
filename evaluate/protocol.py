from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


ERROR_CATEGORIES = ('accuracy', 'fluency', 'tone', 'terminology', 'preservation')
ERROR_SEVERITIES = ('critical', 'major', 'minor')
SCORE_PENALTIES = {'critical': 40, 'major': 15, 'minor': 3}

TRANSLATION_OUTPUT_SCHEMA = {
    'type': 'object',
    'properties': {
        'c': {'type': 'string'},
    },
    'required': ['c'],
    'additionalProperties': False,
}

JUDGE_OUTPUT_SCHEMA = {
    'type': 'object',
    'properties': {
        'errors': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'category': {'type': 'string', 'enum': list(ERROR_CATEGORIES)},
                    'severity': {'type': 'string', 'enum': list(ERROR_SEVERITIES)},
                },
                'required': ['category', 'severity'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['errors'],
    'additionalProperties': False,
}


@dataclass(frozen=True)
class ParsedTranslation:
    valid: bool
    text: str
    error: str | None = None


@dataclass(frozen=True)
class LanguageCheck:
    valid: bool | None
    reason: str
    detected: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class PolicyCheck:
    passed: bool
    violations: list[dict[str, Any]]
    warnings: list[dict[str, Any]]


def parse_translation_output(raw_output: str | None) -> ParsedTranslation:
    if raw_output is None or not str(raw_output).strip():
        return ParsedTranslation(False, '', 'empty_output')

    raw = str(raw_output).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ParsedTranslation(False, '', 'invalid_json')

    if not isinstance(data, dict):
        return ParsedTranslation(False, '', 'json_not_object')
    if 'c' not in data:
        return ParsedTranslation(False, '', 'missing_c')
    if not isinstance(data['c'], str):
        return ParsedTranslation(False, '', 'c_not_string')
    if not data['c'].strip():
        return ParsedTranslation(False, '', 'empty_translation')
    return ParsedTranslation(True, data['c'])


def parse_judge_output(raw_output: str) -> list[dict[str, str]]:
    try:
        data = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise ValueError('judge output is not valid JSON') from exc

    if not isinstance(data, dict) or set(data) != {'errors'}:
        raise ValueError('judge output must contain only the errors field')
    if not isinstance(data['errors'], list):
        raise ValueError('judge errors must be an array')

    errors = []
    for index, item in enumerate(data['errors']):
        if not isinstance(item, dict) or set(item) != {'category', 'severity'}:
            raise ValueError(f'judge error {index} has invalid fields')
        if item['category'] not in ERROR_CATEGORIES:
            raise ValueError(f'judge error {index} has invalid category')
        if item['severity'] not in ERROR_SEVERITIES:
            raise ValueError(f'judge error {index} has invalid severity')
        errors.append({'category': item['category'], 'severity': item['severity']})
    return errors


def score_judge_errors(errors: list[dict[str, str]]) -> int:
    penalty = sum(SCORE_PENALTIES[error['severity']] for error in errors)
    return max(0, 100 - penalty)


def policy_warning_errors(policy: PolicyCheck) -> list[dict[str, str]]:
    errors = []
    for warning in policy.warnings:
        if warning.get('code') == 'number_not_exact':
            errors.append({'category': 'preservation', 'severity': 'minor'})
        elif warning.get('code') == 'source_copy_suspected':
            errors.append({'category': 'accuracy', 'severity': 'minor'})
    return errors


_BUSINESS_LANG_ALIASES = {'ja': 'jp', 'no': 'nb'}
_DETECTOR_LANG_ALIASES = {'jp': 'ja', 'nb': 'no', 'zh-cn': 'zh-cn', 'zh-tw': 'zh-tw'}
_JAPANESE_KANA_RE = re.compile(r'[\u3040-\u30ff]')
_HAN_RE = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')
_CJK_RE = re.compile(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]')


def canonical_language_code(code: str) -> str:
    """Convert dataset-facing aliases to the language codes used by the product."""
    code = code.strip().lower().replace('_', '-')
    return _BUSINESS_LANG_ALIASES.get(code, code)


def normalize_language(code: str) -> str:
    """Convert product codes to the codes emitted by the language detector."""
    code = canonical_language_code(code)
    return _DETECTOR_LANG_ALIASES.get(code, code)


def check_language(text: str, target: str) -> LanguageCheck:
    """Conservative language check; None means the short text is inconclusive."""
    target = normalize_language(target)
    letters = ''.join(ch for ch in text if ch.isalpha())
    if not letters:
        return LanguageCheck(True, 'no_linguistic_content')

    if target == 'ja':
        if _JAPANESE_KANA_RE.search(text):
            return LanguageCheck(True, 'target_script_present', 'ja', 1.0)
        if not _HAN_RE.search(text) and len(letters) >= 8:
            return LanguageCheck(False, 'target_script_missing')
        # Kanji-only text can be Japanese or Chinese; let language detection decide.

    if target.startswith('zh'):
        if _HAN_RE.search(text) and not _JAPANESE_KANA_RE.search(text):
            return LanguageCheck(True, 'target_script_present', target, 1.0)
        if len(letters) >= 8:
            return LanguageCheck(False, 'target_script_missing')
        return LanguageCheck(None, 'too_short_for_language_detection')

    if target != 'ja' and _CJK_RE.search(text):
        return LanguageCheck(False, 'unexpected_script')
    if len(letters) < 8:
        return LanguageCheck(None, 'too_short_for_language_detection')

    try:
        from langdetect import DetectorFactory, detect_langs

        DetectorFactory.seed = 0
        candidates = detect_langs(text)
    except Exception:
        return LanguageCheck(None, 'detector_unavailable_or_inconclusive')

    if not candidates:
        return LanguageCheck(None, 'detector_inconclusive')
    detected = normalize_language(candidates[0].lang)
    confidence = float(candidates[0].prob)
    target_probability = max(
        (float(item.prob) for item in candidates if normalize_language(item.lang) == target),
        default=0.0,
    )
    if detected == target and confidence >= 0.80:
        return LanguageCheck(True, 'detector_match', detected, round(confidence, 4))
    if detected != target and confidence >= 0.95 and target_probability < 0.15:
        # Short Latin-script strings are frequently confused across related languages
        # (for example nl/af, no/da and es/pt). A mismatch is evidence, not a hard fail.
        return LanguageCheck(None, 'detector_mismatch_uncertain', detected, round(confidence, 4))
    return LanguageCheck(None, 'detector_inconclusive', detected, round(confidence, 4))


_URL_RE = re.compile(r'https?://[^\s<>]+|www\.[^\s<>]+', re.IGNORECASE)
_NUMBER_RE = re.compile(r'\d+')
_PLACEHOLDER_RE = re.compile(
    r'\{\{[^{}]+\}\}|\{[^{}]+\}|\$\{[^{}]+\}|%(?:\d+\$)?[a-zA-Z]|<[/!]?[A-Za-z][^>]*>|\[\[[^\]]+\]\]'
)
_MASK_RE = re.compile(r'\*{2,}')
_EMOJI_RE = re.compile(
    '['
    '\U0001F1E6-\U0001F1FF'
    '\U0001F300-\U0001FAFF'
    '\u2600-\u27BF'
    ']'
    '(?:\ufe0f|\u200d['
    '\U0001F300-\U0001FAFF'
    '\u2600-\u27BF'
    '])*'
)


def _extract_preserved_tokens(text: str) -> dict[str, Counter[str]]:
    urls = [token.rstrip('.,!?;:)') for token in _URL_RE.findall(text)]
    return {
        'url': Counter(urls),
        'number': Counter(_NUMBER_RE.findall(text)),
        'placeholder': Counter(_PLACEHOLDER_RE.findall(text)),
        'masked_text': Counter(_MASK_RE.findall(text)),
        'emoji': Counter(_EMOJI_RE.findall(text)),
    }


@lru_cache(maxsize=1)
def load_terminology() -> list[dict[str, str]]:
    path = Path(__file__).with_name('terminology.json')
    return json.loads(path.read_text(encoding='utf-8'))


def _requires_source_copy_hard_fail(text: str) -> bool:
    words = re.findall(r'\w+', text, re.UNICODE)
    return len(words) >= 4 or len(''.join(words)) >= 20


def _has_wrapper_quotes(text: str) -> bool:
    value = text.strip()
    quote_pairs = (('"', '"'), ("'", "'"), ('“', '”'), ('「', '」'), ('『', '』'))
    return any(
        len(value) >= 2 and value.startswith(left) and value.endswith(right)
        for left, right in quote_pairs
    )


def check_policy(
    source: str,
    translation: str,
    source_lang: str,
    target_lang: str,
    reference: str | None = None,
) -> PolicyCheck:
    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    source_tokens = _extract_preserved_tokens(source)
    translated_tokens = _extract_preserved_tokens(translation)

    for token_type, expected in source_tokens.items():
        actual = translated_tokens[token_type]
        if expected != actual:
            issue = {
                'code': 'number_not_exact' if token_type == 'number' else f'{token_type}_not_preserved',
                'expected': dict(expected),
                'actual': dict(actual),
            }
            if token_type == 'number':
                warnings.append(issue)
            else:
                violations.append(issue)

    if _has_wrapper_quotes(translation) and not _has_wrapper_quotes(source):
        violations.append({'code': 'wrapper_quotes_added'})

    source_lang = normalize_language(source_lang)
    target_lang = normalize_language(target_lang)
    terminology_target = {'ja': 'jp', 'no': 'nb'}.get(target_lang, target_lang)
    terminology_source = {'ja': 'jp', 'no': 'nb'}.get(source_lang, source_lang)
    source_folded = source.casefold()
    translation_folded = translation.casefold()
    for entry in load_terminology():
        source_term = entry.get(terminology_source)
        expected_term = entry.get(terminology_target)
        if source_term and expected_term and source_term.casefold() in source_folded:
            if expected_term.casefold() not in translation_folded:
                violations.append({
                    'code': 'terminology_mismatch',
                    'source_term': source_term,
                    'expected_target_term': expected_term,
                })

    source_copied = (
        source_lang != target_lang
        and source.strip().casefold() == translation.strip().casefold()
    )
    reference_confirms = (
        reference is not None
        and reference.strip().casefold() == translation.strip().casefold()
    )
    if source_copied and not reference_confirms:
        if _requires_source_copy_hard_fail(source):
            violations.append({'code': 'source_copied'})
        else:
            warnings.append({'code': 'source_copy_suspected'})

    return PolicyCheck(not violations, violations, warnings)
