"""The echo tool: returns the text it was given.

The simplest possible real tool. Its purpose is to validate the full
agent → gateway → tool → trace round-trip without introducing any
tool-specific complexity (no I/O, no external state, no failure modes
beyond the gateway's own validation).
"""

from pydantic import BaseModel

from marionette.gateway import Tool


class EchoArgs(BaseModel):
    """Arguments for the echo tool."""

    text: str


class EchoResult(BaseModel):
    """Result from the echo tool."""

    text: str


class EchoTool(Tool[EchoArgs, EchoResult]):
    """Returns its input text unchanged.

    Used for smoke-testing the gateway and trace pipeline end-to-end.
    """

    name = "echo"
    description = "Returns the text it was given. Useful for verifying that tool calls work."
    args_schema = EchoArgs
    result_schema = EchoResult

    def run(self, args: EchoArgs) -> EchoResult:
        """Return the input text unchanged."""
        return EchoResult(text=args.text)
