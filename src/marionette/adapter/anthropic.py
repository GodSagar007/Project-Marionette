"""The Anthropic-specific adapter.

Translates between Marionette's provider-agnostic types (Conversation, Message,
Turn, Tool) and Anthropic's API format. This is the only module in the codebase
that imports the anthropic SDK; every other component sees only our types.

For thread one this is the sole adapter. Adding a second provider means adding
a sibling module (e.g. openai.py) with its own translation functions and adapter
class — none of the framework's other components change.
"""

from typing import Any

from marionette.gateway.tool import Tool


def to_anthropic_tool_spec(tool: Tool[Any, Any]) -> dict[str, Any]:
    """Convert a Marionette Tool into Anthropic's tool-definition dict.

    Anthropic expects tools in this shape:
        {"name": str, "description": str, "input_schema": JSON Schema dict}

    The input_schema is generated from the tool's pydantic args_schema using
    pydantic's built-in JSON Schema export. Pydantic includes some cosmetic
    fields (top-level "title", per-property "title") that Anthropic ignores;
    we leave them for simplicity.

    Args:
        tool: The Marionette tool to translate.

    Returns:
        A dict in Anthropic's tool-definition format, ready to pass as one
        element of the `tools` parameter to the messages API.
    """
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.args_schema.model_json_schema(),
    }
