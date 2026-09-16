"""Shared test configuration.

Tests run in offline mode. Anything needing a model or the local stack marks
itself and is excluded from the default run.
"""

import os

os.environ.setdefault("CIP_RUN_MODE", "offline")
