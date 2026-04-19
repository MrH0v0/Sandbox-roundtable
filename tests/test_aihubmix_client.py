from __future__ import annotations

import httpx

from sandbox.clients.aihubmix_client import AIHubMixClient
from sandbox.schemas.config import GenerationConfig


def test_aihubmix_client_extracts_completion_result_with_usage() -> None:
    result = AIHubMixClient._extract_completion_result(
        {
            "choices": [
                {
                    "message": {
                        "content": "answer",
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 34,
                "total_tokens": 154,
            },
        }
    )

    assert result.content == "answer"
    assert result.usage is not None
    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 34
    assert result.usage.total_tokens == 154
    assert result.usage.call_count == 1


def test_aihubmix_client_uses_completion_token_limit_for_gpt5_models() -> None:
    payload = AIHubMixClient._build_payload(
        model="openai/gpt-5.4-mini",
        messages=[{"role": "user", "content": "hello"}],
        generation=GenerationConfig(max_tokens=321),
    )

    assert payload["model"] == "openai/gpt-5.4-mini"
    assert payload["max_completion_tokens"] == 321
    assert "max_tokens" not in payload


def test_aihubmix_client_can_swap_unsupported_token_parameter() -> None:
    adjusted_payload = AIHubMixClient._build_compatibility_payload(
        {
            "model": "provider/model",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 123,
        },
        "Unsupported parameter: 'max_tokens'. Use 'max_completion_tokens' instead.",
    )

    assert adjusted_payload is not None
    assert adjusted_payload["max_completion_tokens"] == 123
    assert "max_tokens" not in adjusted_payload


def test_aihubmix_client_redacts_sensitive_error_response_text() -> None:
    request = httpx.Request("POST", "https://api.example.test/chat/completions")
    response = httpx.Response(
        400,
        request=request,
        text='{"error":"bad request","api_key":"secret-value-123456","prompt":"full private prompt"}',
    )
    error = httpx.HTTPStatusError("bad request", request=request, response=response)

    message = AIHubMixClient._format_error(error)

    assert "secret-value-123456" not in message
    assert "api_key" not in message
    assert "full private prompt" not in message
    assert "status 400" in message
