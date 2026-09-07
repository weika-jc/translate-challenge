from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROMPT_DIR = ROOT / 'prompt'
EVALUATION_PROMPT_DIR = ROOT / 'prompt-eval'
PROMPT_NAMES = (
    'deepseek-v3-2',
    'gemma-3-27b',
    'glm-5',
    'gpt-5-6-luna',
    'gpt-5-6-luna-no-reasoning',
    'gpt-oss-120b',
    'haiku-4-5',
    'haiku-4-5-opt',
    'llama-4-maverick',
    'nova-pro',
)


def _replace_once(
    text: str,
    pattern: str,
    replacement: str,
    prompt_name: str,
    flags: int = 0,
) -> str:
    updated, count = re.subn(pattern, replacement, text, flags=flags)
    if count != 1:
        raise ValueError(
            f'{prompt_name}: expected one policy match for {pattern!r}, found {count}'
        )
    return updated


def _remove_suppression_examples(text: str, prompt_name: str) -> str:
    source = r'(?:you \*{4} \*{4} you|damn it|you bastard)'
    if prompt_name in {'deepseek-v3-2', 'glm-5', 'nova-pro'}:
        pattern = rf'^Input: "{source}" -> [^\n]+\nOutput: [^\n]+\n'
    elif prompt_name in {'gemma-3-27b', 'gpt-oss-120b', 'llama-4-maverick'}:
        pattern = rf'^- Input: "{source}" -> [^\n]+\n  Output: [^\n]+\n'
    elif prompt_name in {'gpt-5-6-luna', 'gpt-5-6-luna-no-reasoning'}:
        pattern = rf'^- Input: `{source} -> [^`\n]+`\n  Output: `[^\n]+`\n'
    elif prompt_name == 'haiku-4-5':
        pattern = rf'^"{source}" → [^\n]+\n\{{[^\n]+\}}\n\n'
    elif prompt_name == 'haiku-4-5-opt':
        pattern = rf'^  <example>\n    <input>{source}.*?^  </example>\n'
    else:
        raise ValueError(f'unsupported evaluation prompt: {prompt_name}')

    expected_count = 3 if prompt_name == 'haiku-4-5' else 2
    updated, count = re.subn(pattern, '', text, flags=re.MULTILINE | re.DOTALL)
    if count != expected_count:
        raise ValueError(
            f'{prompt_name}: expected {expected_count} suppression examples, found {count}'
        )
    return updated


def build_evaluation_prompt(prompt_name: str, production: str) -> str:
    text = production
    if prompt_name == 'deepseek-v3-2':
        text = _replace_once(
            text,
            r'5\. PROFANITY POLICY:\n(?:   - .*\n){3}6\. ESCAPE CHARACTER:',
            '5. ESCAPE CHARACTER:',
            prompt_name,
        )
    elif prompt_name == 'gemma-3-27b':
        text = _replace_once(
            text,
            r'- \*\*Profanity Handling\*\*:[ \t]*\n(?:  - .*\n){3}',
            '',
            prompt_name,
        )
    elif prompt_name == 'glm-5':
        text = _replace_once(
            text,
            r'- PROFANITY & SAFETY:\n(?:  \* .*\n){3}',
            '',
            prompt_name,
        )
    elif prompt_name in {'gpt-5-6-luna', 'gpt-5-6-luna-no-reasoning'}:
        text = _replace_once(
            text,
            r'# Profanity Rules\n.*?(?=# Output Contract\n)',
            '',
            prompt_name,
            re.DOTALL,
        )
    elif prompt_name == 'gpt-oss-120b':
        text = _replace_once(
            text,
            r'### 3\. Safety & Profanity Policy\n(?:- .*\n){3}\n### 4\. Output Formatting',
            '### 3. Output Formatting',
            prompt_name,
        )
    elif prompt_name == 'haiku-4-5':
        text = _replace_once(
            text,
            r'8\. \*\*Profanity handling\*\*:\n(?:   - .*\n){3}9\. \*\*Quotation marks\*\*:',
            '8. **Quotation marks**:',
            prompt_name,
        )
        text = _replace_once(
            text,
            r'10\. \*\*Unrecognized language\*\*:',
            '9. **Unrecognized language**:',
            prompt_name,
        )
    elif prompt_name == 'haiku-4-5-opt':
        text = _replace_once(
            text,
            'filter profanity based on context, and output structured JSON',
            'and output structured JSON',
            prompt_name,
        )
        text = _replace_once(
            text,
            r'6\. Conditional Safety Policy:\n(?:   - .*\n){3}7\. Escaping:',
            '6. Escaping:',
            prompt_name,
        )
    elif prompt_name == 'llama-4-maverick':
        text = _replace_once(
            text,
            r'### CONTEXTUAL RULES \(TRADING & SAFETY\)',
            '### TRADING CONTEXT',
            prompt_name,
        )
        text = _replace_once(
            text,
            r'- \*\*Clear Profanity\*\*:.*\n'
            r'- \*\*Masked Profanity\*\*:.*\n'
            r'- \*\*Mild Contextual Language\*\*:.*\n',
            '',
            prompt_name,
        )
    elif prompt_name == 'nova-pro':
        text = _replace_once(
            text,
            r'- PROFANITY POLICY:[ \t]*\n(?:  \* .*\n){3}',
            '',
            prompt_name,
        )
    else:
        raise ValueError(f'unsupported evaluation prompt: {prompt_name}')

    text = _remove_suppression_examples(text, prompt_name)
    if 'inappropriate language' in text or '不文明用语' in text or '****' in text:
        raise ValueError(f'{prompt_name}: profanity suppression content remains')
    return text


def write_evaluation_prompts() -> None:
    EVALUATION_PROMPT_DIR.mkdir(exist_ok=True)
    for prompt_name in PROMPT_NAMES:
        production = (PROMPT_DIR / prompt_name).read_text(encoding='utf-8')
        evaluation = build_evaluation_prompt(prompt_name, production)
        (EVALUATION_PROMPT_DIR / prompt_name).write_text(evaluation, encoding='utf-8')


if __name__ == '__main__':
    write_evaluation_prompts()
