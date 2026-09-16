"""The fixture-replayed inference adapter, and proof it satisfies the port."""

import json

import pytest
from cip.agents.adapters.fixture import FixtureInference, FixtureNotFound, fixture_key
from cip.core.ports import InferencePort
from cip.core.ports.inference import Message


def test_satisfies_the_port(tmp_path):
    assert isinstance(FixtureInference(tmp_path), InferencePort)


def test_does_not_inherit_from_the_port(tmp_path):
    assert InferencePort not in FixtureInference.__mro__


async def test_replays_a_recorded_completion(tmp_path):
    messages = [Message(role="user", content="hello")]
    key = fixture_key(messages, system="be terse")
    (tmp_path / f"{key}.json").write_text(
        json.dumps({"text": "hi", "input_tokens": 3, "output_tokens": 1, "model": "fixture-1"}),
        encoding="utf-8",
    )

    completion = await FixtureInference(tmp_path).complete(messages, system="be terse")

    assert completion.text == "hi"
    assert completion.model == "fixture-1"
    assert completion.replayed is True


async def test_different_requests_get_different_keys():
    a = fixture_key([Message(role="user", content="hello")])
    b = fixture_key([Message(role="user", content="goodbye")])
    assert a != b


async def test_missing_fixture_raises(tmp_path):
    with pytest.raises(FixtureNotFound):
        await FixtureInference(tmp_path).complete([Message(role="user", content="?")])
