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

    OFFLINE = "offline"  # recorded fixtures, no network, what tests use
    LOCAL = "local"  # real local stack, ollama, local vector store
    CLOUD = "cloud"  # managed services, not implemented yet


class Settings:
    """Process configuration, read once at import time."""

    def __init__(self) -> None:
        self.run_mode = RunMode(os.getenv("CIP_RUN_MODE", RunMode.OFFLINE))
        self.data_dir = Path(os.getenv("CIP_DATA_DIR", "data")).resolve()
        self._identity_salt = os.getenv("CIP_IDENTITY_SALT")

    @property
    def is_offline(self) -> bool:
        return self.run_mode is RunMode.OFFLINE

    @property
    def identity_salt(self) -> str:
        """Salt for hashing identity values (see IdentityHandling.HASH).

        Read from the environment, never hardcoded: a salt baked into the
        source would make every contact_hash reversible by anyone who has
        read the repository, which is exactly the exposure hashing exists
        to prevent. The offline fallback below is a fixed, published
        value used only so tests are deterministic without needing an
        environment - it must never be relied on outside CIP_RUN_MODE=offline.
        """
        if self._identity_salt is not None:
            return self._identity_salt
        if self.run_mode is RunMode.OFFLINE:
            return "offline-fixture-salt-not-for-production-use"
        raise RuntimeError(
            "CIP_IDENTITY_SALT is not set. Refusing to fall back to a "
            "hardcoded salt outside offline mode - set it in the "
            "environment before running ingestion in local or cloud mode."
        )


settings = Settings()
