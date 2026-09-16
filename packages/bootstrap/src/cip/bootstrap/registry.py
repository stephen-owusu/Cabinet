"""One cached factory per port, each branching on run mode.

Adapters are imported inside the arm that selects them, so importing the
registry never drags in a dependency for a mode this process will not
run. Callers get a port back, never a concrete class - swapping an
adapter is a change to one match arm and nothing else.
"""

from __future__ import annotations

from functools import cache

from cip.core.config import RunMode, settings
from cip.core.ports import InferencePort, VectorStorePort


@cache
def inference() -> InferencePort:
    match settings.run_mode:
        case RunMode.OFFLINE:
            from cip.agents.adapters.fixture import FixtureInference

            return FixtureInference(settings.data_dir / "fixtures" / "inference")
        case RunMode.LOCAL:
            raise NotImplementedError("OllamaInference is not written yet")
        case RunMode.CLOUD:
            raise NotImplementedError("BedrockInference is not written yet")


@cache
def vector_store() -> VectorStorePort:
    match settings.run_mode:
        case RunMode.OFFLINE:
            from cip.retrieval.adapters.memory import InMemoryVectorStore

            return InMemoryVectorStore()
        case RunMode.LOCAL:
            raise NotImplementedError("LocalVectorStore is not written yet")
        case RunMode.CLOUD:
            raise NotImplementedError("ManagedVectorStore is not written yet")
