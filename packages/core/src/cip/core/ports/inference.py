"""Inference port.

Implemented by: recorded fixtures, ollama, a hosted API, and eventually
Bedrock. Nothing outside an adapter module knows which.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class Message:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    replayed: bool = False


@runtime_checkable
class InferencePort(Protocol):
    async def complete(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> Completion: ...

    @property
    def model_id(self) -> str:
        """Stable identifier, recorded in the run manifest."""
        ...
