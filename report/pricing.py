from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BillingMode = Literal['standard', 'cached_prompt']


@dataclass(frozen=True)
class ModelPricing:
    """单价单位：美元/百万 token（USD per 1,000,000 tokens）。"""

    input_per_million: float
    output_per_million: float
    billing_mode: BillingMode = 'standard'
    cached_input_ratio: float = 0.25


# 模型名 = CSV 文件名去掉 .csv 的 stem
PRICES: dict[str, ModelPricing] = {
    'nova-pro': ModelPricing(
        input_per_million=0.8000,
        output_per_million=3.2000,
        billing_mode='cached_prompt',
        cached_input_ratio=0.25,
    ),
    'gpt-oss-120b': ModelPricing(input_per_million=0.1500, output_per_million=0.6000),
    'gpt-5-6-luna': ModelPricing(
        input_per_million=0.2200,
        output_per_million=1.3200,
        billing_mode='cached_prompt',
        cached_input_ratio=0.10,
    ),
    'gemma-3-27b': ModelPricing(input_per_million=0.2300, output_per_million=0.3800),
    'gemma-3-27b-reasoning': ModelPricing(input_per_million=0.2300, output_per_million=0.3800),
    'haiku-4-5': ModelPricing(input_per_million=1.0000, output_per_million=5.0000),
    'haiku-4-5-opt': ModelPricing(input_per_million=1.0000, output_per_million=5.0000),
    'deepseek-v3-2': ModelPricing(input_per_million=0.6200, output_per_million=1.8500),
    'llama-4-maverick': ModelPricing(input_per_million=0.2400, output_per_million=0.9700),
    'glm-5': ModelPricing(input_per_million=1.0000, output_per_million=3.2000),
}

DEFAULT_PRICING = ModelPricing(input_per_million=0.0, output_per_million=0.0)


def get_pricing(model_name: str) -> ModelPricing:
    return PRICES.get(model_name, DEFAULT_PRICING)


def calc_cost(
    input_tokens: int | float | None,
    output_tokens: int | float | None,
    total_tokens: int | float | None,
    pricing: ModelPricing,
) -> float:
    inp = int(input_tokens or 0)
    out = int(output_tokens or 0)
    pin = pricing.input_per_million
    pout = pricing.output_per_million

    if pricing.billing_mode == 'cached_prompt' and total_tokens is not None:
        total = int(total_tokens)
        cached = max(0, total - inp - out)
        cached_rate = pin * pricing.cached_input_ratio
        return (inp / 1_000_000) * pin + (cached / 1_000_000) * cached_rate + (out / 1_000_000) * pout

    return (inp / 1_000_000) * pin + (out / 1_000_000) * pout


# backward compatible alias
get_price = get_pricing
PricePerMillion = ModelPricing
