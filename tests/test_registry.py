"""The composition root: one cached factory per port, branching on run mode."""

from collections.abc import Iterator

import pytest
from cip.bootstrap.registry import inference, vector_store
from cip.core.config import RunMode, settings
from cip.core.ports import InferencePort, VectorStorePort


@pytest.fixture(autouse=True)
def _clear_caches() -> Iterator[None]:
    """Each test gets a cold registry, whatever ran before it."""
    inference.cache_clear()
    vector_store.cache_clear()
    yield
    inference.cache_clear()
    vector_store.cache_clear()


def test_offline_adapters_satisfy_the_ports():
    assert isinstance(inference(), InferencePort)
    assert isinstance(vector_store(), VectorStorePort)


def test_adapters_are_cached():
    """Two callers asking for a port get the same instance, not two stores."""
    assert inference() is inference()
    assert vector_store() is vector_store()


@pytest.mark.parametrize("run_mode", [RunMode.LOCAL, RunMode.CLOUD])
def test_unimplemented_modes_name_the_missing_adapter(run_mode, monkeypatch):
    monkeypatch.setattr(settings, "run_mode", run_mode)

    with pytest.raises(NotImplementedError, match="not written yet"):
        inference()
    with pytest.raises(NotImplementedError, match="not written yet"):
        vector_store()
