from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class TokenUsage(BaseModel):
    """Normalized token usage for one or more LLM calls."""

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    call_count: int = Field(default=0, ge=0)
    estimated: bool = False

    @model_validator(mode="after")
    def fill_total_tokens(self) -> "TokenUsage":
        if self.total_tokens == 0 and (self.input_tokens or self.output_tokens):
            self.total_tokens = self.input_tokens + self.output_tokens
        if self.call_count == 0 and self.total_tokens:
            self.call_count = 1
        return self

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "TokenUsage | None":
        if not isinstance(payload, dict):
            return None

        input_tokens = payload.get("input_tokens", payload.get("prompt_tokens", 0))
        output_tokens = payload.get(
            "output_tokens",
            payload.get("completion_tokens", 0),
        )
        total_tokens = payload.get("total_tokens", 0)
        return cls(
            input_tokens=int(input_tokens or 0),
            output_tokens=int(output_tokens or 0),
            total_tokens=int(total_tokens or 0),
            call_count=int(payload.get("call_count") or 1),
            estimated=bool(payload.get("estimated") or False),
        )

    def merged(self, other: "TokenUsage | None") -> "TokenUsage":
        if other is None:
            return self.model_copy()
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            call_count=self.call_count + other.call_count,
            estimated=bool(self.estimated or other.estimated),
        )


class ChatCompletionResult(BaseModel):
    """Text content plus optional token usage from an OpenAI-compatible response."""

    content: str
    usage: TokenUsage | None = None
