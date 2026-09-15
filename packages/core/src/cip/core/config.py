"""Run mode and settings.

One environment variable, CIP_RUN_MODE, decides which implementations the
system uses. Nothing else in the codebase branches on run mode.
"""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path


class RunMode(StrEnum):
    """How the system is wired for this process."""

    OFFLINE = "offline"   # recorded fixtures, no network, what tests use
    LOCAL = "local"       # real local stack, ollama, local vector store
    CLOUD = "cloud"       # managed services, not implemented yet


class Settings:
    """Process configuration, read once at import time."""

    def __init__(self) -> None:
        self.run_mode = RunMode(os.getenv("CIP_RUN_MODE", RunMode.OFFLINE))
        self.data_dir = Path(os.getenv("CIP_DATA_DIR", "data")).resolve()

    @property
    def is_offline(self) -> bool:
        return self.run_mode is RunMode.OFFLINE


settings = Settings()