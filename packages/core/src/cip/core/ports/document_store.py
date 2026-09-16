"""Document store port. SQLite now, DynamoDB later.

Holds response metadata, workflow status and review outcomes. Deliberately
key-value shaped rather than relational, so a later move does not require
unpicking joins.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DocumentStorePort(Protocol):
    async def put(self, collection: str, key: str, item: dict[str, Any]) -> None: ...

    async def get(self, collection: str, key: str) -> dict[str, Any] | None: ...

    async def delete(self, collection: str, key: str) -> None: ...

    def query(
        self, collection: str, *, where: dict[str, Any] | None = None
    ) -> AsyncIterator[dict[str, Any]]: ...
