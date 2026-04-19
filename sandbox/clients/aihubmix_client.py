from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx

from sandbox.core.config import AppSettings
from sandbox.schemas.config import GenerationConfig
from sandbox.schemas.usage import ChatCompletionResult, TokenUsage


class AIHubMixClient:
    """Thin async client for OpenAI-compatible AIHubMix endpoints."""

    RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
    SENSITIVE_FIELD_PATTERN = re.compile(
        r'(?i)("?(?:api[_-]?key|authorization|token|secret|password|prompt|messages)"?\s*[:=]\s*)'
        r'(".*?"|[^,\s}]+)'
    )
    BEARER_PATTERN = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
    API_KEY_PATTERN = re.compile(r"\b(?:sk|ak)-[A-Za-z0-9._-]{8,}\b")

    def __init__(self, settings: AppSettings):
        self.base_url = settings.aihubmix_base_url.rstrip("/")
        self.api_key = settings.aihubmix_api_key
        self.max_retries = settings.max_retries
        self.retry_backoff_seconds = settings.retry_backoff_seconds
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.request_timeout_seconds)
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    async def chat_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        generation: GenerationConfig,
    ) -> ChatCompletionResult:
        """Call one OpenAI-style chat completion endpoint with retry protection."""

        if not self.api_key:
            raise RuntimeError("AIHUBMIX_API_KEY is not configured.")

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(
            model=model,
            messages=messages,
            generation=generation,
        )

        attempt = 0
        compatibility_adjustments = 0
        while attempt <= self.max_retries:
            try:
                response = await self.client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                return self._extract_completion_result(data)
            except httpx.HTTPStatusError as exc:
                adjusted_payload = self._build_compatibility_payload(
                    payload,
                    exc.response.text,
                )
                if (
                    exc.response.status_code == 400
                    and adjusted_payload is not None
                    and compatibility_adjustments < 3
                ):
                    payload = adjusted_payload
                    compatibility_adjustments += 1
                    continue

                should_retry = self._should_retry(exc, attempt)
                if not should_retry:
                    raise RuntimeError(self._format_error(exc)) from exc

                await asyncio.sleep(self.retry_backoff_seconds * (attempt + 1))
                attempt += 1
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                should_retry = self._should_retry(exc, attempt)
                if not should_retry:
                    raise RuntimeError(self._format_error(exc)) from exc

                await asyncio.sleep(self.retry_backoff_seconds * (attempt + 1))
                attempt += 1

        raise RuntimeError("AIHubMix request failed after retries.")

    @classmethod
    def _build_payload(
        cls,
        *,
        model: str,
        messages: list[dict[str, str]],
        generation: GenerationConfig,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": generation.temperature,
        }
        payload[
            cls._resolve_max_tokens_parameter(
                model,
                generation.max_tokens_parameter,
            )
        ] = generation.max_tokens

        if generation.top_p is not None:
            payload["top_p"] = generation.top_p

        return payload

    @staticmethod
    def _resolve_max_tokens_parameter(model: str, configured_parameter: str) -> str:
        if configured_parameter != "auto":
            return configured_parameter

        normalized_model = model.strip().lower().rsplit("/", 1)[-1]
        if normalized_model.startswith(("gpt-5", "o1", "o3", "o4")):
            return "max_completion_tokens"
        return "max_tokens"

    @staticmethod
    def _build_compatibility_payload(
        payload: dict[str, Any],
        response_text: str,
    ) -> dict[str, Any] | None:
        message = response_text.lower()
        adjusted = dict(payload)

        if "unsupported" in message and "max_tokens" in message and "max_tokens" in adjusted:
            adjusted["max_completion_tokens"] = adjusted.pop("max_tokens")

        elif (
            "unsupported" in message
            and "max_completion_tokens" in message
            and "max_completion_tokens" in adjusted
        ):
            adjusted["max_tokens"] = adjusted.pop("max_completion_tokens")

        for optional_parameter in ("temperature", "top_p"):
            if "unsupported" in message and optional_parameter in message:
                adjusted.pop(optional_parameter, None)

        return adjusted if adjusted != payload else None

    def _should_retry(self, exc: Exception, attempt: int) -> bool:
        if attempt >= self.max_retries:
            return False

        if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
            return True

        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in self.RETRYABLE_STATUS_CODES

        return False

    @staticmethod
    def _format_error(exc: Exception) -> str:
        if isinstance(exc, httpx.HTTPStatusError):
            response_text = AIHubMixClient._sanitize_error_text(exc.response.text)
            return (
                f"AIHubMix request failed with status {exc.response.status_code}: "
                f"{response_text}"
            )
        return f"AIHubMix request failed: {AIHubMixClient._sanitize_error_text(str(exc))}"

    @classmethod
    def _sanitize_error_text(cls, text: str) -> str:
        cleaned = str(text or "").replace("\r", " ").replace("\n", " ").strip()
        cleaned = cls.BEARER_PATTERN.sub("Bearer [REDACTED]", cleaned)
        cleaned = cls.API_KEY_PATTERN.sub("[REDACTED_API_KEY]", cleaned)
        cleaned = cls.SENSITIVE_FIELD_PATTERN.sub("[REDACTED_FIELD]", cleaned)
        return cleaned[:300] or "response body redacted"

    @staticmethod
    def _extract_content(payload: dict[str, Any]) -> str:
        return AIHubMixClient._extract_completion_result(payload).content

    @staticmethod
    def _extract_completion_result(payload: dict[str, Any]) -> ChatCompletionResult:
        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError("AIHubMix response has no choices.")

        message = choices[0].get("message") or {}
        content = message.get("content", "")

        if isinstance(content, str):
            rendered_content = content.strip()
        elif isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")).strip())
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            rendered_content = "\n".join(part for part in parts if part).strip()
        else:
            raise RuntimeError("AIHubMix response content format is not supported.")

        return ChatCompletionResult(
            content=rendered_content,
            usage=TokenUsage.from_payload(payload.get("usage")),
        )
