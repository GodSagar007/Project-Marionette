"""Tool gateway for Marionette.

Receives tool calls from the agent, logs intent before routing, invokes the
registered tool, and records the outcome — all to the trace.
"""

from marionette.gateway.registry import ToolRegistry
from marionette.gateway.tool import Tool, ToolError, ToolErrorType

__all__ = ["Tool", "ToolError", "ToolErrorType", "ToolRegistry"]
