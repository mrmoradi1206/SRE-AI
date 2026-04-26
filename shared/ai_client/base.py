from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class AIClientError(RuntimeError):
    pass


@dataclass(slots=True)
class AIMessage:
    role: str
    content: str


@dataclass(slots=True)
class AICompletionRequest:
    model: str
    messages: list[AIMessage]
    temperature: float = 0.2
    max_tokens: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AICompletionResponse:
    content: str
    raw_response: dict[str, Any]
    provider: str
    model: str


class BaseAIClient:
    provider_name = 'base'

    async def complete(self, request: AICompletionRequest) -> AICompletionResponse:
        raise NotImplementedError
