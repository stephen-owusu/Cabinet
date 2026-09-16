"""Tools: the functions an agent can call, exposed over MCP.

Adapts ToolTransportPort. Tool schemas come from mcp.json at the repo
root, not from this package, so the transport can change without the
contract changing. Depends on cip-core; nothing here talks to a model,
that is the agent loop's job.
"""
