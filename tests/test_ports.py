"""Ports are protocols, and nothing checks that until something looks."""

from typing import Protocol

import pytest
from cip.core import ports
from cip.core.config import RunMode, settings


def test_all_ports_exported():
    assert len(ports.__all__) == 7


@pytest.mark.parametrize("name", ports.__all__)
def test_every_port_is_a_protocol(name):
    port = getattr(ports, name)
    assert Protocol in port.__mro__, f"{name} is not a Protocol"


def test_every_port_name_ends_with_port():
    for name in ports.__all__:
        assert name.endswith("Port"), f"{name} breaks the naming convention"


def test_tests_run_offline():
    assert settings.run_mode is RunMode.OFFLINE
