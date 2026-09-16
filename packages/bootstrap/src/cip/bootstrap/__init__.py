"""Bootstrap: the composition root.

The only package allowed to import concrete adapters from more than one
other package and wire them together. Everything else asks for a port;
this decides, per run mode, what answers it.
"""

from cip.bootstrap.registry import inference, vector_store

__all__ = ["inference", "vector_store"]
