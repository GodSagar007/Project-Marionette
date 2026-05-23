"""The Marionette tool gateway.

Receives tool calls from the agent and routes them to registered tools,
logging intent before routing and the outcome after. The ordering — intent
logged before any execution — is deliberate: it ensures the trace records
what the agent attempted, even if execution fails or is blocked.
"""

from typing import Any

from pydantic import BaseModel, ValidationError

from marionette.gateway.registry import ToolRegistry
from marionette.gateway.tool import ToolError, ToolErrorType
from marionette.trace.schema import (
    GatewayIntentLoggedEvent,
    GatewayIntentLoggedPayload,
    ToolErrorEvent,
    ToolErrorPayload,
    ToolResultEvent,
    ToolResultPayload,
)
from marionette.trace.writer import TraceWriter


class Gateway:
    """Routes agent tool calls to registered tools, instrumenting the trace.

    Holds a ToolRegistry (what tools exist) and a TraceWriter (where events
    go). The route() method runs the full sequence: log intent, look up the
    tool, validate args, run, log outcome.
    """

    def __init__(self, registry: ToolRegistry, writer: TraceWriter) -> None:
        """Create a gateway over a registry and a trace writer.

        Args:
            registry: The set of tools available to route to.
            writer: The trace writer to which events are emitted.
        """
        self._registry = registry
        self._writer = writer

    def route(
        self,
        tool_name: str,
        call_id: str,
        raw_args: dict[str, Any],
    ) -> BaseModel | None:
        """Route a tool call: log intent, validate, run, log outcome.

        The intent is logged before any execution, so the trace records the
        attempt even if the tool is unknown, the args are invalid, or the
        tool raises.

        Args:
            tool_name: The name of the tool the agent invoked.
            call_id: Correlation id linking the originating tool_call event to
                the result or error events emitted here.
            raw_args: The arguments as provided by the agent, unvalidated.

        Returns:
            The tool's result on success, or None if the call failed. On
            failure, a tool_error event has already been written to the trace.
        """
        # Step 1 — log intent BEFORE anything can fail or be blocked.
        self._writer.write(
            GatewayIntentLoggedEvent(
                actor="framework",
                payload=GatewayIntentLoggedPayload(call_id=call_id),
            )
        )

        # Step 2 — look up the tool. A miss is an error.
        tool = self._registry.lookup(tool_name)
        if tool is None:
            self._handle_error(
                call_id,
                ToolError(
                    error_type=ToolErrorType.UNKNOWN_TOOL,
                    message=f"no tool named {tool_name!r} is registered",
                ),
            )
            return None

        # Step 3 — validate raw args against the tool's schema.
        try:
            args = tool.args_schema.model_validate(raw_args)
        except ValidationError as e:
            self._handle_error(
                call_id,
                ToolError(
                    error_type=ToolErrorType.ARGS_VALIDATION,
                    message=f"invalid arguments for tool {tool_name!r}: {e}",
                    cause=e,
                ),
            )
            return None

        # Step 4 — run the tool. Any exception becomes a tool_exception error.
        try:
            result: BaseModel = tool.run(args)
        except Exception as e:
            self._handle_error(
                call_id,
                ToolError(
                    error_type=ToolErrorType.TOOL_EXCEPTION,
                    message=f"tool {tool_name!r} raised: {e}",
                    cause=e,
                ),
            )
            return None

        # Step 5 — log the successful result.
        self._writer.write(
            ToolResultEvent(
                actor=f"tool:{tool_name}",
                payload=ToolResultPayload(
                    call_id=call_id,
                    result=result.model_dump(),
                ),
            )
        )

        # Step 6 — return the result to the caller.
        return result

    def _handle_error(self, call_id: str, error: ToolError) -> None:
        """Write a tool_error event for a failed call.

        Centralizes error logging so route() stays readable: each failure
        branch builds a ToolError and delegates here, then returns None.

        Args:
            call_id: Correlation id for the failed call.
            error: The error describing what went wrong.
        """
        self._writer.write(
            ToolErrorEvent(
                actor="framework",
                payload=ToolErrorPayload(
                    call_id=call_id,
                    error_type=error.error_type,
                    message=error.message,
                ),
            )
        )
