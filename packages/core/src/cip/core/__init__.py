"""Domain model, ports and configuration.

The architectural spine. Defines what the system works with and what
capabilities it needs, never how those capabilities are provided. Imports
nothing outside the standard library and pydantic.

Every other package depends on this one. This one depends on nothing.
"""

from cip.core.config import RunMode, Settings, settings

__all__ = ["RunMode", "Settings", "settings"]
