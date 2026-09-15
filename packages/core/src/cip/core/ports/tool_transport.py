"""Tool transport port.

In-process for tests, a local MCP server for development, a managed gateway
later. Tool schemas are generated from mcp.json in every case, so the
transport changes and the contract does not.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResult:
    content: Any
    is_error: bool = False


@runtime_checkable
class ToolTransportPort(Protocol):
    async def list_tools(self) -> Sequence[ToolSpec]: ...

    async def call(
        self, name: str, arguments: dict[str, Any], *, principal: str
    ) -> ToolResult: ...