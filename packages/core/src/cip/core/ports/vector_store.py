"""Vector store port.

Semantic search only. Keyword search is a separate port, deliberately.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class VectorHit:
    chunk_id: str
    response_id: str
    score: float
    text: str
    metadata: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class VectorStorePort(Protocol):
    async def upsert(
        self,
        chunk_ids: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        texts: Sequence[str],
        metadatas: Sequence[dict[str, str]],
    ) -> None: ...

    async def search(
        self,
        embedding: Sequence[float],
        *,
        limit: int = 20,
        where: dict[str, str] | None = None,
    ) -> list[VectorHit]: ...

    async def delete(self, chunk_ids: Sequence[str]) -> None: ...
