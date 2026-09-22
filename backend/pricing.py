"""Loads backend/pricing.yaml and turns a harness invocation's token
usage into a dollar estimate for the cost panel (CUSTOM cost_delta
events). This is an ESTIMATE for the live UI, not a billing record --
see scope-and-architecture.md §4.6 on why Observability/this panel is
not a substitute for Cost Explorer.
"""
import os

import yaml

_PRICING_PATH = os.path.join(os.path.dirname(__file__), "pricing.yaml")
with open(_PRICING_PATH) as f:
    _PRICING = yaml.safe_load(f)

_MODELS = _PRICING.get("models", {})

# Populated by main.py whenever a model override is used for a turn, so
# usage_to_cost() prices against the model that actually ran rather than
# always assuming the harness default.
_current_model_id = None


def set_current_model(model_id: str | None) -> None:
    global _current_model_id
    _current_model_id = model_id


DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-6"


def usage_to_cost(usage: dict) -> dict:
    model_id = _current_model_id or DEFAULT_MODEL_ID
    rates = _MODELS.get(model_id, _MODELS.get(DEFAULT_MODEL_ID, {}))
    input_tokens = usage.get("inputTokens", 0)
    output_tokens = usage.get("outputTokens", 0)
    cost = (
        input_tokens * rates.get("input_per_million", 0) / 1_000_000
        + output_tokens * rates.get("output_per_million", 0) / 1_000_000
    )
    return {
        "modelId": model_id,
        "label": rates.get("label", model_id),
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "costUsd": round(cost, 6),
    }
