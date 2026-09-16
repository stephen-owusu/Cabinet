"""In-memory vector store.

Brute force cosine similarity over a dictionary. Correct, slow, and entirely
adequate for unit tests against corpora of a few hundred responses.

Its job is to let retrieval code run with no database, so that swapping in a
real index tests the index rather than the calling code.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from cip.core.ports.vector_store import VectorHit


@dataclass(slots=True)
class _Record:
    embedding: tuple[float, ...]
    text: str
    metadata: dict[str, str]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Similarity between two vectors, 1.0 identical, 0.0 unrelated."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return 0.0 if na == 0 or nb == 0 else dot / (na * nb)


class InMemoryVectorStore:
    """Satisfies VectorStorePort."""

    def __init__(self) -> None:
        self._records: dict[str, _Record] = {}

    async def upsert(
        self,
        chunk_ids: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        texts: Sequence[str],
        metadatas: Sequence[dict[str, str]],
    ) -> None:
        for cid, emb, text, meta in zip(chunk_ids, embeddings, texts, metadatas, strict=True):
            self._records[cid] = _Record(tuple(emb), text, dict(meta))

    async def search(
        self,
        embedding: Sequence[float],
        *,
        limit: int = 20,
        where: dict[str, str] | None = None,
    ) -> list[VectorHit]:
        hits = [
            VectorHit(
                chunk_id=cid,
                response_id=rec.metadata.get("response_id", ""),
                score=_cosine(embedding, rec.embedding),
                text=rec.text,
                metadata=rec.metadata,
            )
            for cid, rec in self._records.items()
            if where is None or all(rec.metadata.get(k) == v for k, v in where.items())
        ]
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]

    async def delete(self, chunk_ids: Sequence[str]) -> None:
        for cid in chunk_ids:
            self._records.pop(cid, None)
