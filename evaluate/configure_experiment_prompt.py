from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import boto3


REGION = 'us-west-2'


def _public_model_id(model_id: str) -> str:
    if ':inference-profile/' in model_id:
        return model_id.rsplit('/', 1)[-1]
    return model_id


def build_variant(
    prompt_text: str,
    model_id: str,
    use_cache: bool,
    use_reasoning: bool = False,
) -> dict:
    system = [{'text': prompt_text}]
    if use_cache:
        system.append({'cachePoint': {'type': 'default'}})
    variant = {
        'name': 'variantOne',
        'modelId': model_id,
        'templateType': 'CHAT',
        'templateConfiguration': {
            'chat': {
                'inputVariables': [{'name': 'input'}],
                'messages': [{
                    'role': 'user',
                    'content': [{'text': '{{input}}'}],
                }],
                'system': system,
            },
        },
    }
    if use_reasoning:
        # This is the exact payload stored by the Bedrock Prompt Management
        # console when its single Reasoning toggle is enabled for Gemma 3.
        variant['inferenceConfiguration'] = {
            'text': {'temperature': 1.0, 'topP': 1.0},
        }
        variant['additionalModelRequestFields'] = {
            'thinking': {'type': 'enabled', 'budget_tokens': 1024},
        }
    return variant


def configure(
    prompt_identifier: str,
    prompt_path: Path,
    model_id: str,
    use_cache: bool,
    use_reasoning: bool = False,
) -> dict:
    prompt_text = prompt_path.read_text(encoding='utf-8')
    session = boto3.Session(profile_name='aigc')
    client = session.client('bedrock-agent', region_name=REGION)
    current = client.get_prompt(
        promptIdentifier=prompt_identifier,
        promptVersion='DRAFT',
    )
    variant = build_variant(prompt_text, model_id, use_cache, use_reasoning)
    client.update_prompt(
        promptIdentifier=prompt_identifier,
        name=current['name'],
        description=current.get('description', ''),
        defaultVariant=variant['name'],
        variants=[variant],
    )
    verified = client.get_prompt(
        promptIdentifier=prompt_identifier,
        promptVersion='DRAFT',
    )
    verified_variant = next(
        item for item in verified['variants']
        if item['name'] == verified['defaultVariant']
    )
    verified_text = next(
        item['text']
        for item in verified_variant['templateConfiguration']['chat']['system']
        if 'text' in item
    )
    if verified_variant['modelId'] != model_id or verified_text != prompt_text:
        raise RuntimeError('experiment Prompt verification failed after update')
    return {
        'prompt_id': 'managed-prompt',
        'model_id': _public_model_id(verified_variant['modelId']),
        'prompt_file': str(prompt_path),
        'prompt_sha256': hashlib.sha256(verified_text.encode('utf-8')).hexdigest(),
        'cache_point': any(
            'cachePoint' in item
            for item in verified_variant['templateConfiguration']['chat']['system']
        ),
        'reasoning': verified_variant.get('additionalModelRequestFields'),
        'updated_at': verified['updatedAt'].isoformat(),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Configure an experiment Prompt Management Draft',
    )
    parser.add_argument(
        '--prompt-id', default=os.environ.get('BEDROCK_PROMPT_ID'),
        help='Prompt ID (defaults to BEDROCK_PROMPT_ID)',
    )
    parser.add_argument('--prompt-file', type=Path, required=True)
    parser.add_argument('--model-id', required=True)
    parser.add_argument(
        '--cache', action=argparse.BooleanOptionalAction, default=True,
        help='place a cache point after the system prompt (default: enabled)',
    )
    parser.add_argument(
        '--reasoning', action=argparse.BooleanOptionalAction, default=False,
        help='enable the Bedrock Prompt Management Reasoning configuration',
    )
    args = parser.parse_args()
    if not args.prompt_id:
        parser.error('--prompt-id or BEDROCK_PROMPT_ID is required')
    return args


def main() -> None:
    args = _parse_args()
    print(json.dumps(
        configure(
            args.prompt_id,
            args.prompt_file,
            args.model_id,
            args.cache,
            args.reasoning,
        ),
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == '__main__':
    main()
