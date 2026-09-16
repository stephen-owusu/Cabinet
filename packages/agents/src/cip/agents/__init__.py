"""Agents: the orchestration loop that calls a model and its tools.

Owns the adapters for InferencePort, because deciding when and how to talk
to a model is an orchestration concern, not a retrieval or tooling one.
Depends on cip-core.
"""
