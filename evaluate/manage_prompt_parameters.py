from __future__ import annotations

import argparse
import copy
import json
import os
from collections.abc import Callable

import boto3


DEFAULT_PROFILE = 'aigc'
DEFAULT_REGION = 'us-west-2'
UPDATABLE_VARIANT_FIELDS = frozenset({
    'name',
    'modelId',
    'templateType',
    'templateConfiguration',
    'metadata',
    'genAiResource',
    'inferenceConfiguration',
    'additionalModelRequestFields',
})


def _default_variant(prompt: dict) -> dict:
    default_name = prompt.get('defaultVariant')
    variant = next(
        (
            item for item in prompt.get('variants', [])
            if item.get('name') == default_name
        ),
        None,
    )
    if variant is None:
        raise ValueError('Prompt Draft does not have a default variant')
    return variant


def _public_model_id(model_id: str | None) -> str:
    if not model_id:
        return '(not set)'
    if ':inference-profile/' in model_id:
        return model_id.rsplit('/', 1)[-1]
    if model_id.startswith('arn:'):
        return model_id.rsplit('/', 1)[-1].rsplit(':', 1)[-1]
    return model_id


def _masked_identifier(identifier: str) -> str:
    if len(identifier) <= 4:
        return '*' * len(identifier)
    return f'{identifier[:2]}...{identifier[-2:]}'


def _parameters(variant: dict) -> dict[str, dict | None]:
    inference_configuration = variant.get('inferenceConfiguration')
    if inference_configuration is None:
        inference = None
    else:
        unsupported = set(inference_configuration) - {'text'}
        if unsupported:
            raise ValueError(
                'Only text inference configuration is supported by this editor; '
                f'found: {sorted(unsupported)}'
            )
        inference = copy.deepcopy(inference_configuration.get('text'))

    additional = copy.deepcopy(variant.get('additionalModelRequestFields'))
    return {'inference': inference, 'additional': additional}


def _normalized_parameters(state: dict[str, dict | None]) -> dict[str, dict | None]:
    return {
        'inference': copy.deepcopy(state.get('inference') or None),
        'additional': copy.deepcopy(state.get('additional') or None),
    }


def _display_prompt(
    prompt: dict,
    state: dict[str, dict | None],
    write: Callable[[str], None] = print,
) -> None:
    variant = _default_variant(prompt)
    write('')
    write(f"Prompt: {_masked_identifier(prompt.get('id', ''))} (DRAFT)")
    write(f"Name: {prompt.get('name', '')}")
    write(f"Default variant: {variant.get('name', '')}")
    write(f"Model: {_public_model_id(variant.get('modelId'))}")
    write(f"Template type: {variant.get('templateType', '')}")
    write('Template:')
    write(json.dumps(
        variant.get('templateConfiguration'),
        ensure_ascii=False,
        indent=2,
    ))
    write('Parameters:')
    write(json.dumps(_normalized_parameters(state), ensure_ascii=False, indent=2))


def _split_path(path: str) -> tuple[str, list[str]]:
    parts = [part for part in path.split('.') if part]
    if not parts or parts[0] not in {'inference', 'additional'}:
        raise ValueError('path must start with inference or additional')
    return parts[0], parts[1:]


def _set_path(state: dict[str, dict | None], path: str, value) -> None:
    root, parts = _split_path(path)
    if not parts:
        if not isinstance(value, dict):
            raise ValueError(f'{root} must be a JSON object')
        state[root] = copy.deepcopy(value)
        return

    current = state.get(root)
    if current is None:
        current = {}
        state[root] = current
    if not isinstance(current, dict):
        raise ValueError(f'{root} is not a JSON object')
    for part in parts[:-1]:
        child = current.get(part)
        if child is None:
            child = {}
            current[part] = child
        if not isinstance(child, dict):
            raise ValueError(f'{part} is not a JSON object')
        current = child
    current[parts[-1]] = value


def _delete_path(state: dict[str, dict | None], path: str) -> None:
    root, parts = _split_path(path)
    if not parts:
        state[root] = None
        return

    current = state.get(root)
    if not isinstance(current, dict):
        return
    parents = []
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            return
        parents.append((current, part))
        current = child
    current.pop(parts[-1], None)
    for parent, key in reversed(parents):
        child = parent.get(key)
        if isinstance(child, dict) and not child:
            parent.pop(key)
    if not state[root]:
        state[root] = None


def _help(write: Callable[[str], None] = print) -> None:
    write('')
    write('Commands:')
    write('  show')
    write('  set inference.maxTokens 300')
    write('  set inference.stopSequences ["END"]')
    write('  set additional.thinking {"type":"enabled","budget_tokens":1024}')
    write('  delete inference.temperature')
    write('  delete additional.top_k')
    write('  delete inference            # remove the entire section')
    write('  luna-defaults [maxTokens]   # keep maxTokens only; default 300')
    write('  apply                       # preview, confirm, and update Draft')
    write('  quit')
    write('Values after set must be valid JSON.')


def _preview(
    before: dict[str, dict | None],
    after: dict[str, dict | None],
    write: Callable[[str], None] = print,
) -> None:
    write('')
    write('Current parameters:')
    write(json.dumps(_normalized_parameters(before), ensure_ascii=False, indent=2))
    write('New parameters:')
    write(json.dumps(_normalized_parameters(after), ensure_ascii=False, indent=2))


def interactive_edit(
    prompt: dict,
    read: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
) -> dict[str, dict | None] | None:
    original = _parameters(_default_variant(prompt))
    state = copy.deepcopy(original)
    _display_prompt(prompt, state, write)
    _help(write)

    while True:
        try:
            line = read('prompt-params> ').strip()
        except (EOFError, KeyboardInterrupt):
            write('\nCancelled; no changes were made.')
            return None
        if not line:
            continue
        command, _, arguments = line.partition(' ')
        command = command.casefold()
        try:
            if command == 'show':
                _display_prompt(prompt, state, write)
            elif command == 'help':
                _help(write)
            elif command == 'set':
                path, separator, raw_value = arguments.strip().partition(' ')
                if not separator:
                    raise ValueError('usage: set <path> <JSON value>')
                _set_path(state, path, json.loads(raw_value))
            elif command in {'delete', 'clear'}:
                if not arguments.strip():
                    raise ValueError('usage: delete <path>')
                _delete_path(state, arguments.strip())
            elif command == 'luna-defaults':
                raw_max_tokens = arguments.strip() or '300'
                max_tokens = int(raw_max_tokens)
                if max_tokens <= 0:
                    raise ValueError('maxTokens must be positive')
                state = {
                    'inference': {'maxTokens': max_tokens},
                    'additional': None,
                }
            elif command == 'apply':
                normalized = _normalized_parameters(state)
                if normalized == _normalized_parameters(original):
                    write('No parameter changes to apply.')
                    continue
                _preview(original, normalized, write)
                confirmation = read('Type APPLY to update the Draft: ').strip()
                if confirmation != 'APPLY':
                    write('Not applied.')
                    continue
                return normalized
            elif command in {'quit', 'exit'}:
                write('Cancelled; no changes were made.')
                return None
            else:
                write(f'Unknown command: {command}. Type help for usage.')
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            write(f'Invalid command: {exc}')


def _variant_for_update(variant: dict) -> dict:
    return {
        key: copy.deepcopy(value)
        for key, value in variant.items()
        if key in UPDATABLE_VARIANT_FIELDS
    }


def _prompt_content_snapshot(prompt: dict) -> dict:
    variants = []
    for source in prompt.get('variants', []):
        variant = _variant_for_update(source)
        variant.pop('inferenceConfiguration', None)
        variant.pop('additionalModelRequestFields', None)
        variants.append(variant)
    return {
        'name': prompt.get('name', ''),
        'description': prompt.get('description'),
        'customerEncryptionKeyArn': prompt.get('customerEncryptionKeyArn'),
        'defaultVariant': prompt.get('defaultVariant'),
        'variants': variants,
    }


def _full_editable_snapshot(prompt: dict) -> dict:
    snapshot = _prompt_content_snapshot(prompt)
    snapshot['parameters'] = _parameters(_default_variant(prompt))
    return snapshot


def build_updated_variants(
    prompt: dict,
    state: dict[str, dict | None],
) -> list[dict]:
    default_name = prompt['defaultVariant']
    normalized = _normalized_parameters(state)
    variants = []
    for source in prompt.get('variants', []):
        variant = _variant_for_update(source)
        if variant.get('name') == default_name:
            variant.pop('inferenceConfiguration', None)
            variant.pop('additionalModelRequestFields', None)
            if normalized['inference'] is not None:
                variant['inferenceConfiguration'] = {
                    'text': normalized['inference'],
                }
            if normalized['additional'] is not None:
                variant['additionalModelRequestFields'] = normalized['additional']
        variants.append(variant)
    return variants


def update_parameters(
    client,
    prompt_identifier: str,
    original: dict,
    state: dict[str, dict | None],
) -> dict:
    current = client.get_prompt(
        promptIdentifier=prompt_identifier,
        promptVersion='DRAFT',
    )
    if _full_editable_snapshot(current) != _full_editable_snapshot(original):
        raise RuntimeError(
            'Prompt Draft changed after it was displayed; reload before applying'
        )

    update = {
        'promptIdentifier': prompt_identifier,
        'name': current['name'],
        'defaultVariant': current['defaultVariant'],
        'variants': build_updated_variants(current, state),
    }
    if current.get('description') is not None:
        update['description'] = current['description']
    if current.get('customerEncryptionKeyArn') is not None:
        update['customerEncryptionKeyArn'] = current['customerEncryptionKeyArn']
    client.update_prompt(**update)
    verified = client.get_prompt(
        promptIdentifier=prompt_identifier,
        promptVersion='DRAFT',
    )
    if _prompt_content_snapshot(verified) != _prompt_content_snapshot(current):
        raise RuntimeError('Prompt content or model changed during parameter update')
    if _normalized_parameters(_parameters(_default_variant(verified))) != (
        _normalized_parameters(state)
    ):
        raise RuntimeError('Prompt parameters do not match after update')
    return verified


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Inspect and interactively edit Bedrock Prompt Draft parameters',
    )
    parser.add_argument(
        '--prompt-id', default=os.environ.get('BEDROCK_PROMPT_ID'),
        help='Prompt ID (defaults to BEDROCK_PROMPT_ID; never stored)',
    )
    parser.add_argument('--profile', default=DEFAULT_PROFILE)
    parser.add_argument('--region', default=DEFAULT_REGION)
    parser.add_argument(
        '--show-only', action='store_true',
        help='display the current Draft and exit without an edit prompt',
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    prompt_identifier = args.prompt_id
    if not prompt_identifier:
        prompt_identifier = input('Prompt ID: ').strip()
    if not prompt_identifier:
        raise SystemExit('Prompt ID is required')

    session = boto3.Session(profile_name=args.profile)
    client = session.client('bedrock-agent', region_name=args.region)
    prompt = client.get_prompt(
        promptIdentifier=prompt_identifier,
        promptVersion='DRAFT',
    )
    if args.show_only:
        _display_prompt(prompt, _parameters(_default_variant(prompt)))
        return

    state = interactive_edit(prompt)
    if state is None:
        return
    verified = update_parameters(client, prompt_identifier, prompt, state)
    print('Draft parameters updated and verified.')
    print(json.dumps(
        _normalized_parameters(_parameters(_default_variant(verified))),
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == '__main__':
    main()
