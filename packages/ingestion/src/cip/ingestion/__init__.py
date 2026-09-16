"""Ingestion: raw consultation documents in, indexable chunks out.

Parsing, cleaning and chunking, upstream of anything that indexes or
embeds. A sibling of retrieval: same layer, depends only on cip-core, and
does not depend on retrieval or retrieval on it.
"""
