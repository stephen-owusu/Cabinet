"""Session memory port. SQLite now, a managed memory service later."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MemoryPort(Protocol):
    async def append(self, session_id: str, event: dict[str, Any]) -> None: ...

    async def history(self, session_id: str, *, limit: int = 100) -> Sequence[dict[str, Any]]: ...

    async def clear(self, session_id: str) -> None: ...
