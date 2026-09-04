import asyncio
import json
import time
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, SSOError

from .prompt import build_judge_prompt
from .protocol import JUDGE_OUTPUT_SCHEMA, parse_judge_output, score_judge_errors

session = boto3.Session(profile_name='aigc')
bedrock_runtime = session.client(
    service_name='bedrock-runtime',
    region_name='us-west-2',
    config=Config(
        retries={'max_attempts': 3, 'mode': 'standard'},
        connect_timeout=10,
        read_timeout=30,
    ),
)
judge_runtime = session.client(
    service_name='bedrock-runtime',
    region_name='us-west-2',
    config=Config(
        retries={'max_attempts': 3, 'mode': 'standard'},
        connect_timeout=10,
        # A new structured-output schema can take longer to compile on first use.
        read_timeout=300,
    ),
)
sonnet_model_id = 'arn:aws:bedrock:us-west-2:686465264859:inference-profile/us.anthropic.claude-sonnet-4-6'
_structured_output_supported: bool | None = None


async def _converse(client=bedrock_runtime, **kwargs):
    return await asyncio.to_thread(client.converse, **kwargs)


async def translate(model_id: str, txt: str, tgt: str) -> dict | None:
    print(f'[debug] translate {txt} -> {tgt}')
    message = f'{txt} -> {tgt}'
    start = time.perf_counter()
    response = await _converse(modelId=model_id, promptVariables={ 'input': { 'text': message } })
    latency_ms = round((time.perf_counter() - start) * 1000, 2)

    text = None
    for content in response['output']['message']['content']:
        if 'text' in content:
            text = content['text']
            break
    if text is None:
        return None

    usage = response.get('usage', {})
    return {
        'text': text,
        'input_tokens': usage.get('inputTokens'),
        'output_tokens': usage.get('outputTokens'),
        'total_tokens': usage.get('totalTokens'),
        'latency_ms': latency_ms,
    }


async def invoke_generic_model(model_id: str, txt: str, structured: bool = True) -> dict:
    messages = [{ 'role': 'user', 'content': [{ 'text': txt }] }]
    kwargs = {
        'modelId': model_id,
        'messages': messages,
        'inferenceConfig': {'temperature': 0, 'maxTokens': 256},
    }
    if structured:
        kwargs['outputConfig'] = {
            'textFormat': {
                'type': 'json_schema',
                'structure': {
                    'jsonSchema': {
                        'schema': json.dumps(JUDGE_OUTPUT_SCHEMA, ensure_ascii=False),
                        'name': 'translation_errors',
                        'description': 'MQM-lite translation error categories and severities',
                    },
                },
            },
        }

    start = time.perf_counter()
    response = await _converse(client=judge_runtime, **kwargs)
    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    text = next(
        (item['text'] for item in response['output']['message']['content'] if 'text' in item),
        None,
    )
    if text is None:
        raise ValueError('judge response does not contain text')
    usage = response.get('usage', {})
    return {
        'text': text,
        'input_tokens': usage.get('inputTokens'),
        'output_tokens': usage.get('outputTokens'),
        'total_tokens': usage.get('totalTokens'),
        'latency_ms': latency_ms,
        'structured': structured,
    }


def _can_fallback_from_structured_output(exc: Exception) -> bool:
    if not isinstance(exc, ClientError):
        return False
    error = exc.response.get('Error', {})
    if error.get('Code') != 'ValidationException':
        return False
    message = str(error.get('Message', '')).lower()
    return any(term in message for term in ('outputconfig', 'structured output', 'json_schema'))


async def rate(raw: str, trans: str, tgt: str, ref: str | None = None) -> dict:
    global _structured_output_supported

    message = build_judge_prompt(raw, tgt, trans, ref)
    structured = _structured_output_supported is not False
    last_error = None
    last_raw = None
    for _ in range(3):
        try:
            response = await invoke_generic_model(sonnet_model_id, message, structured=structured)
            last_raw = response['text']
            errors = parse_judge_output(response['text'])
            acceptable = not any(
                error['severity'] in ('major', 'critical') for error in errors
            )
            if structured:
                _structured_output_supported = True
            return {
                'success': True,
                'acceptable': acceptable,
                'errors': errors,
                'score': score_judge_errors(errors),
                'raw': response['text'],
                'error': None,
                'input_tokens': response['input_tokens'],
                'output_tokens': response['output_tokens'],
                'total_tokens': response['total_tokens'],
                'latency_ms': response['latency_ms'],
                'structured': response['structured'],
            }
        except Exception as e:
            if structured and _can_fallback_from_structured_output(e):
                structured = False
                _structured_output_supported = False
                print(f'[debug] structured output unavailable, falling back to JSON prompt: {e}')
                continue
            last_error = str(e)
            print(f'[debug] rate failed: {e}')
            if isinstance(e, SSOError):
                break
    return {
        'success': False,
        'acceptable': None,
        'errors': [],
        'score': None,
        'raw': last_raw,
        'error': last_error or 'unknown_judge_error',
        'input_tokens': None,
        'output_tokens': None,
        'total_tokens': None,
        'latency_ms': None,
        'structured': structured,
    }
