"""Fixture-replayed inference.

Offline mode never calls a model. It replays the recorded completion for
the exact request it has seen before, keyed by a hash of that request, so
tests are deterministic and free. Recording those fixtures is a separate
concern; this adapter only replays.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from cip.core.ports.inference import Completion, Message


class FixtureNotFound(LookupError):
    """No recorded completion matches this request."""


def fixture_key(messages: Sequence[Message], system: str | None = None) -> str:
    """Deterministic id for a request, stable across process runs."""
    payload = json.dumps(
        {
            "system": system,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class FixtureInference:
    """Satisfies InferencePort by replaying recorded completions from disk."""

    def __init__(self, fixtures_dir: Path, *, model_id: str = "fixture") -> None:
        self._dir = fixtures_dir
        self._model_id = model_id

    @property
    def model_id(self) -> str:
        return self._model_id

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> Completion:
        key = fixture_key(messages, system)
        path = self._dir / f"{key}.json"
        if not path.exists():
            raise FixtureNotFound(f"no fixture recorded for request {key!r} in {self._dir}")

        recorded = json.loads(path.read_text(encoding="utf-8"))
        return Completion(
            text=recorded["text"],
            input_tokens=recorded["input_tokens"],
            output_tokens=recorded["output_tokens"],
            model=recorded.get("model", self._model_id),
            replayed=True,
        )
