"""Tool abstraction for the Marionette gateway.

A Tool is the contract between the agent and any capability it can invoke.
Concrete tools subclass `Tool`, declare their metadata as class attributes,
and implement `run()`. The gateway validates args against the tool's schema
before invoking `run()`, so tools never see raw dicts.
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel


class ToolErrorType:
    """Canonical error_type values for ToolErrorPayload.

    Class constants rather than an Enum, to keep JSON serialization simple
    and avoid pydantic-Enum quirks. Add new categories by extension only —
    existing values must not change once any trace records them.
    """

    UNKNOWN_TOOL = "unknown_tool"
    ARGS_VALIDATION = "args_validation"
    TOOL_EXCEPTION = "tool_exception"


class ToolError(Exception):
    """Raised by the gateway when a tool invocation fails.

    Carries an error_type from ToolErrorType for trace recording, plus an
    optional cause exception (the original exception if a tool's run() raised).
    The gateway catches this internally and converts it to a tool_error event;
    callers of the gateway usually do not need to catch it.
    """

    def __init__(
        self,
        error_type: str,
        message: str,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.cause = cause


class Tool(ABC):
    """Abstract base class for tools that the agent can invoke.

    Subclasses must declare:
        name: stable identifier the agent uses to invoke the tool
        description: human-readable explanation shown to the LLM
        args_schema: pydantic model for arguments
        result_schema: pydantic model for the return value

    And must implement:
        run(args): the actual tool behavior
    """

    name: str
    description: str
    args_schema: type[BaseModel]
    result_schema: type[BaseModel]

    @abstractmethod
    def run(self, args: BaseModel) -> BaseModel:
        """Execute the tool's behavior with validated arguments.

        Args:
            args: An instance of self.args_schema.

        Returns:
            An instance of self.result_schema.

        Raises:
            Exception: Tools may raise any exception. The gateway catches
                them and converts to a tool_error event with
                ToolErrorType.TOOL_EXCEPTION.
        """
