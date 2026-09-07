import asyncio
import json
import os
import random
import time
import boto3
from botocore.config import Config
from botocore.exceptions import (
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)

from .prompt import build_judge_prompt
from .protocol import (
    JUDGE_OUTPUT_SCHEMA,
    TRANSLATION_OUTPUT_SCHEMA,
    canonical_language_code,
    parse_judge_output,
    parse_translation_output,
    score_judge_errors,
)

session = boto3.Session(profile_name='aigc')
RUNTIME_MAX_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 0.5
RETRY_MAX_DELAY_SECONDS = 8.0
RETRYABLE_CLIENT_ERROR_CODES = frozenset({
    'InternalServerException',
    'ModelNotReadyException',
    'ModelTimeoutException',
    'ServiceUnavailableException',
    'ThrottlingException',
})
RETRYABLE_TRANSPORT_ERRORS = (
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)

bedrock_runtime = session.client(
    service_name='bedrock-runtime',
    region_name='us-west-2',
    config=Config(
        # Keep retries visible and bounded in this module instead of multiplying
        # application attempts by botocore's internal attempts.
        retries={'total_max_attempts': 1, 'mode': 'standard'},
        connect_timeout=10,
        read_timeout=30,
    ),
)
judge_runtime = session.client(
    service_name='bedrock-runtime',
    region_name='us-west-2',
    config=Config(
        retries={'total_max_attempts': 1, 'mode': 'standard'},
        connect_timeout=10,
        # A new structured-output schema can take longer to compile on first use.
        read_timeout=300,
    ),
)
sts_client = session.client(
    service_name='sts',
    region_name='us-west-2',
    config=Config(
        retries={'max_attempts': 1, 'mode': 'standard'},
        connect_timeout=10,
        read_timeout=10,
    ),
)
sonnet_model_id = os.environ.get(
    'BEDROCK_JUDGE_MODEL_ID', 'us.anthropic.claude-sonnet-4-6',
)
_structured_output_supported: bool | None = None


async def _converse(client=bedrock_runtime, **kwargs):
    return await asyncio.to_thread(client.converse, **kwargs)


def _response_text(response: dict) -> str | None:
    return next(
        (
            item['text']
            for item in response.get('output', {}).get('message', {}).get('content', [])
            if 'text' in item
        ),
        None,
    )


def _translation_output_status(response: dict) -> tuple[bool, str | None]:
    parsed = parse_translation_output(_response_text(response))
    return parsed.valid, parsed.error


def _judge_output_status(response: dict) -> tuple[bool, str | None]:
    text = _response_text(response)
    if text is None:
        return False, 'response_does_not_contain_text'
    try:
        parse_judge_output(text)
    except Exception as exc:
        return False, str(exc)
    return True, None


def _sum_usage(responses: list[dict], key: str) -> int | None:
    values = [response.get('usage', {}).get(key) for response in responses]
    values = [value for value in values if value is not None]
    return sum(values) if values else None


def _invocation_metrics(
    *,
    attempts: int,
    responses: list[dict],
    started_at: float,
    first_call_success: bool | None,
    first_output_valid: bool | None,
    final_output_valid: bool | None,
    final_output_error: str | None,
) -> dict:
    return {
        'attempts': attempts,
        'retries': max(0, attempts - 1),
        'first_call_success': first_call_success,
        'first_output_valid': first_output_valid,
        'final_output_valid': final_output_valid,
        'final_output_error': final_output_error,
        'recovered_by_retry': attempts > 1 and final_output_valid is True,
        # Usage includes every completed response, including malformed responses
        # that triggered a retry. This keeps cost accounting honest.
        'input_tokens': _sum_usage(responses, 'inputTokens'),
        'output_tokens': _sum_usage(responses, 'outputTokens'),
        'total_tokens': _sum_usage(responses, 'totalTokens'),
        'latency_ms': round((time.perf_counter() - started_at) * 1000, 2),
    }


def _is_retryable_model_error(exc: Exception) -> bool:
    if isinstance(exc, RETRYABLE_TRANSPORT_ERRORS):
        return True
    if not isinstance(exc, ClientError):
        return False
    code = exc.response.get('Error', {}).get('Code')
    return code in RETRYABLE_CLIENT_ERROR_CODES


async def _converse_with_retry(
    client=bedrock_runtime,
    validate_response=None,
    **kwargs,
):
    started_at = time.perf_counter()
    responses = []
    first_call_success = None
    first_output_valid = None
    final_output_valid = None
    final_output_error = None

    for attempt in range(1, RUNTIME_MAX_ATTEMPTS + 1):
        try:
            response = await _converse(client=client, **kwargs)
        except Exception as exc:
            if attempt == 1:
                first_call_success = False
            metrics = _invocation_metrics(
                attempts=attempt,
                responses=responses,
                started_at=started_at,
                first_call_success=first_call_success,
                first_output_valid=first_output_valid,
                final_output_valid=None,
                final_output_error=str(exc),
            )
            # Preserve attempt/cost information even when the public API keeps
            # raising the original botocore exception.
            setattr(exc, 'evaluation_metrics', metrics)
            if attempt == RUNTIME_MAX_ATTEMPTS or not _is_retryable_model_error(exc):
                raise
            retry_reason = f'transient model error: {exc}'
        else:
            responses.append(response)
            if attempt == 1:
                first_call_success = True
            if validate_response is None:
                final_output_valid, final_output_error = True, None
            else:
                final_output_valid, final_output_error = validate_response(response)
            if attempt == 1:
                first_output_valid = final_output_valid

            metrics = _invocation_metrics(
                attempts=attempt,
                responses=responses,
                started_at=started_at,
                first_call_success=first_call_success,
                first_output_valid=first_output_valid,
                final_output_valid=final_output_valid,
                final_output_error=final_output_error,
            )
            if final_output_valid or attempt == RUNTIME_MAX_ATTEMPTS:
                return response, metrics
            retry_reason = f'unusable model output: {final_output_error}'

        if attempt < RUNTIME_MAX_ATTEMPTS:
            ceiling = min(
                RETRY_MAX_DELAY_SECONDS,
                RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)),
            )
            # Full jitter prevents the eight workers from retrying in lockstep.
            delay = random.uniform(0, ceiling)
            print(
                f'[debug] {retry_reason}; retrying attempt '
                f'{attempt + 1}/{RUNTIME_MAX_ATTEMPTS} in {delay:.2f}s'
            )
            await asyncio.sleep(delay)


async def check_aws_identity() -> dict:
    """Fail before model calls when the configured AWS session is unavailable."""
    return await asyncio.to_thread(sts_client.get_caller_identity)


def _structured_output_config(schema: dict, name: str, description: str) -> dict:
    return {
        'textFormat': {
            'type': 'json_schema',
            'structure': {
                'jsonSchema': {
                    'schema': json.dumps(
                        schema, ensure_ascii=False, separators=(',', ':'),
                    ),
                    'name': name,
                    'description': description,
                },
            },
        },
    }


async def translate(
    model_id: str,
    txt: str,
    tgt: str,
    structured: bool = False,
) -> dict | None:
    tgt = canonical_language_code(tgt)
    print(f'[debug] translate {txt} -> {tgt}')
    message = f'{txt} -> {tgt}'
    kwargs = {
        'modelId': model_id,
        'promptVariables': {'input': {'text': message}},
    }
    if structured:
        kwargs['outputConfig'] = _structured_output_config(
            TRANSLATION_OUTPUT_SCHEMA,
            'translation_result',
            'Translated text in the c field',
        )

    # Structured and prompt-only models use the same semantics: invalid output is
    # retried, but a valid low-quality translation is never cherry-picked.
    response, metrics = await _converse_with_retry(
        validate_response=_translation_output_status,
        **kwargs,
    )
    text = _response_text(response)
    return {
        'text': text,
        'structured': structured,
        **metrics,
    }


async def invoke_generic_model(model_id: str, txt: str, structured: bool = True) -> dict:
    messages = [{ 'role': 'user', 'content': [{ 'text': txt }] }]
    kwargs = {
        'modelId': model_id,
        'messages': messages,
        'inferenceConfig': {'temperature': 0, 'maxTokens': 256},
    }
    if structured:
        kwargs['outputConfig'] = _structured_output_config(
            JUDGE_OUTPUT_SCHEMA,
            'translation_errors',
            'MQM-lite translation error categories and severities',
        )

    response, metrics = await _converse_with_retry(
        client=judge_runtime,
        validate_response=_judge_output_status,
        **kwargs,
    )
    return {
        'text': _response_text(response),
        'structured': structured,
        **metrics,
    }


def _exception_metrics(exc: Exception) -> dict:
    return getattr(exc, 'evaluation_metrics', {})


def _merge_invocation_metrics(first: dict, second: dict) -> dict:
    def add_optional(left, right):
        values = [value for value in (left, right) if value is not None]
        return sum(values) if values else None

    attempts = (first.get('attempts') or 0) + (second.get('attempts') or 0)
    return {
        'attempts': attempts,
        'retries': max(0, attempts - 1),
        'first_call_success': first.get('first_call_success'),
        'first_output_valid': first.get('first_output_valid'),
        'final_output_valid': second.get('final_output_valid'),
        'final_output_error': second.get('final_output_error'),
        'recovered_by_retry': attempts > 1 and second.get('final_output_valid') is True,
        'input_tokens': add_optional(first.get('input_tokens'), second.get('input_tokens')),
        'output_tokens': add_optional(first.get('output_tokens'), second.get('output_tokens')),
        'total_tokens': add_optional(first.get('total_tokens'), second.get('total_tokens')),
        'latency_ms': add_optional(first.get('latency_ms'), second.get('latency_ms')),
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

    message = build_judge_prompt(raw, canonical_language_code(tgt), trans, ref)
    structured = _structured_output_supported is not False
    prior_metrics = None
    try:
        response = await invoke_generic_model(sonnet_model_id, message, structured=structured)
    except Exception as exc:
        if structured and _can_fallback_from_structured_output(exc):
            prior_metrics = _exception_metrics(exc)
            structured = False
            _structured_output_supported = False
            print(f'[debug] structured output unavailable, falling back to JSON prompt: {exc}')
            try:
                response = await invoke_generic_model(
                    sonnet_model_id, message, structured=False,
                )
            except Exception as fallback_exc:
                print(f'[debug] rate failed: {fallback_exc}')
                metrics = _merge_invocation_metrics(
                    prior_metrics, _exception_metrics(fallback_exc),
                )
                return _failed_rate_result(
                    str(fallback_exc), structured=False, metrics=metrics,
                )
        else:
            print(f'[debug] rate failed: {exc}')
            return _failed_rate_result(
                str(exc), structured=structured, metrics=_exception_metrics(exc),
            )

    metrics = response
    if prior_metrics is not None:
        metrics = _merge_invocation_metrics(prior_metrics, response)

    try:
        errors = parse_judge_output(response['text'])
    except Exception as exc:
        # The retry loop has already exhausted all format attempts.
        print(f'[debug] invalid judge output: {exc}')
        return _failed_rate_result(
            str(exc), structured=response['structured'], response=response, metrics=metrics,
        )

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
        'input_tokens': metrics.get('input_tokens'),
        'output_tokens': metrics.get('output_tokens'),
        'total_tokens': metrics.get('total_tokens'),
        'latency_ms': metrics.get('latency_ms'),
        'structured': response['structured'],
        'attempts': metrics.get('attempts'),
        'retries': metrics.get('retries'),
        'first_call_success': metrics.get('first_call_success'),
        'first_output_valid': metrics.get('first_output_valid'),
        'recovered_by_retry': metrics.get('recovered_by_retry'),
    }


def _failed_rate_result(
    error: str,
    structured: bool,
    response: dict | None = None,
    metrics: dict | None = None,
) -> dict:
    metrics = metrics or response or {}
    return {
        'success': False,
        'acceptable': None,
        'errors': [],
        'score': None,
        'raw': response.get('text') if response else None,
        'error': error or 'unknown_judge_error',
        'input_tokens': metrics.get('input_tokens'),
        'output_tokens': metrics.get('output_tokens'),
        'total_tokens': metrics.get('total_tokens'),
        'latency_ms': metrics.get('latency_ms'),
        'structured': structured,
        'attempts': metrics.get('attempts'),
        'retries': metrics.get('retries'),
        'first_call_success': metrics.get('first_call_success'),
        'first_output_valid': metrics.get('first_output_valid'),
        'recovered_by_retry': metrics.get('recovered_by_retry'),
    }
