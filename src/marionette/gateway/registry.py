"""Tool registry for the Marionette gateway.

Holds the mapping from tool name to Tool instance. Responsible only for
storage and retrieval — error semantics (what a missing tool means) live
in the gateway, not here.
"""
from pydantic import BaseModel

from marionette.gateway.tool import Tool


class ToolRegistry:
    """A name-indexed collection of registered tools.

    Not responsible for error handling on lookup misses: lookup() returns
    None and the caller (the gateway) decides what a miss means.
    """

    def __init__(self) -> None:
        """Create an empty registry."""
        self._tools: dict[str, Tool[BaseModel, BaseModel]] = {}

    def register(self, tool: Tool[BaseModel, BaseModel]) -> None:
        """Register a tool under its own declared name.

        Args:
            tool: The tool instance to register. Its `name` attribute is
                used as the registry key.

        Raises:
            ValueError: If a tool with the same name is already registered.
        """
        if tool.name in self._tools:
            raise ValueError(f"a tool named {tool.name!r} is already registered")
        self._tools[tool.name] = tool

    def lookup(self, name: str) -> Tool[BaseModel, BaseModel] | None:
        """Return the tool registered under `name`, or None if not found.

        Args:
            name: The tool name to look up.

        Returns:
            The registered Tool, or None if no tool has that name.
        """
        return self._tools.get(name)

    def names(self) -> list[str]:
        """Return the names of all registered tools, sorted.

        Useful for building tool manifests and for diagnostic messages.
        """
        return sorted(self._tools)

    def __contains__(self, name: str) -> bool:
        """Support `name in registry` membership checks."""
        return name in self._tools

    def __len__(self) -> int:
        """Support `len(registry)` to count registered tools."""
        return len(self._tools)
