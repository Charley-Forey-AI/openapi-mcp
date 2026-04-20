"""OpenAPI MCP Builder.

An MCP server that registers an OpenAPI spec with the Trimble Agentic AI
Platform and returns a hosted MCP gateway URL.
"""

from openapi_mcp_builder.server import mcp

__all__ = ["mcp"]
__version__ = "0.1.0"
