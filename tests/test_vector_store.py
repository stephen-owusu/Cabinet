"""The in-memory vector store, and proof that it satisfies the port."""

import pytest
from cip.core.ports import VectorStorePort
from cip.retrieval.adapters.memory import InMemoryVectorStore


def test_satisfies_the_port():
    """Structural typing: it matches without inheriting."""
    assert isinstance(InMemoryVectorStore(), VectorStorePort)


def test_does_not_inherit_from_the_port():
    """The adapter does not know the port exists. That is the point."""
    assert VectorStorePort not in InMemoryVectorStore.__mro__


async def test_stores_and_finds():
    store = InMemoryVectorStore()
    await store.upsert(
        chunk_ids=["a", "b"],
        embeddings=[[1.0, 0.0], [0.0, 1.0]],
        texts=["about cats", "about dogs"],
        metadatas=[{"response_id": "r1"}, {"response_id": "r2"}],
    )

    hits = await store.search([1.0, 0.0], limit=1)

    assert len(hits) == 1
    assert hits[0].chunk_id == "a"
    assert hits[0].response_id == "r1"
    assert hits[0].score == pytest.approx(1.0)


async def test_filters_on_metadata():
    store = InMemoryVectorStore()
    await store.upsert(
        chunk_ids=["a", "b"],
        embeddings=[[1.0, 0.0], [1.0, 0.0]],
        texts=["one", "two"],
        metadatas=[{"response_id": "r1"}, {"response_id": "r2"}],
    )

    hits = await store.search([1.0, 0.0], where={"response_id": "r2"})

    assert len(hits) == 1
    assert hits[0].chunk_id == "b"


async def test_mismatched_lengths_raise():
    """strict=True on zip. Silent misalignment would mean wrong citations."""
    store = InMemoryVectorStore()
    with pytest.raises(ValueError):
        await store.upsert(
            chunk_ids=["a", "b"],
            embeddings=[[1.0, 0.0]],
            texts=["one", "two"],
            metadatas=[{}, {}],
        )
