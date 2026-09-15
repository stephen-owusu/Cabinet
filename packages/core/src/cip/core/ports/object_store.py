"""Object store port. Local filesystem now, S3 later."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable


@runtime_checkable
class ObjectStorePort(Protocol):
    async def put(self, key: str, data: bytes, *, content_type: str | None = None) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def exists(self, key: str) -> bool: ...

    def list(self, prefix: str) -> AsyncIterator[str]: ...