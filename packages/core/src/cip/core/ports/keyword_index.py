"""Keyword index port.

BM25 over the response corpus. Separate from the vector store because a
managed vector store may not offer keyword search, and consultation
responses use precise policy terminology that embeddings blur.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class KeywordHit:
    chunk_id: str
    response_id: str
    score: float
    text: str


@runtime_checkable
class KeywordIndexPort(Protocol):
    async def index(self, chunk_ids: Sequence[str], texts: Sequence[str]) -> None: ...

    async def search(self, query: str, *, limit: int = 20) -> list[KeywordHit]: ...