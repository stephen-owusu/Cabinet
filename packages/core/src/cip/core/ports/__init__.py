"""Ports: the capabilities the system needs, stated as protocols.

Adding a port is a design decision. Adding an adapter is not.
"""

from cip.core.ports.document_store import DocumentStorePort
from cip.core.ports.inference import InferencePort
from cip.core.ports.keyword_index import KeywordIndexPort
from cip.core.ports.memory import MemoryPort
from cip.core.ports.object_store import ObjectStorePort
from cip.core.ports.tool_transport import ToolTransportPort
from cip.core.ports.vector_store import VectorStorePort

__all__ = [
    "DocumentStorePort",
    "InferencePort",
    "KeywordIndexPort",
    "MemoryPort",
    "ObjectStorePort",
    "ToolTransportPort",
    "VectorStorePort",
]
