"""The send_message tool: agent-to-agent communication.

Communication is a Tool rather than a conversation-layer feature, so it
routes through the gateway like any other call — logged before routed, args
schema-validated, failures recorded — and so a scenario can remove the
channel by omitting the tool from an agent's tool list. That omission is the
active control for any claim about whether communication caused coordination.

The tool queues into ctx.bus. It does not deliver: delivery timing is the
runner's business, and an agent should not be able to choose when its message
lands.
"""

from pydantic import BaseModel

from marionette.bus import PendingMessage
from marionette.context import RunContext
from marionette.gateway import Tool


class SendMessageArgs(BaseModel):
    """Arguments for the send_message tool."""

    to: str
    text: str


class SendMessageResult(BaseModel):
    """Confirmation that a message was accepted for delivery.

    Deliberately says accepted, not delivered. The sender learns that the
    recipient was valid and the message queued — not when, or whether, it was
    read. Telling a sender more than that would leak delivery timing into the
    agent's context and confound reveal semantics.
    """

    to: str
    accepted: bool = True


class SendMessageTool(Tool[SendMessageArgs, SendMessageResult]):
    """Sends a message to another agent in the scenario.

    The roster is fixed when the scenario is written, so it is legitimate
    frozen state on the tool instance — unlike per-run state, which lives on
    the RunContext.
    """

    name = "send_message"
    description = (
        "Send a message to another agent. Provide the recipient's id in 'to' "
        "and the message body in 'text'."
    )
    args_schema = SendMessageArgs
    result_schema = SendMessageResult

    def __init__(self, roster: list[str]) -> None:
        """Args:
        roster: Every agent id that may be addressed.
        """
        self._roster = frozenset(roster)

    def run(self, args: SendMessageArgs, ctx: RunContext) -> SendMessageResult:
        """Queue a message for delivery to another agent.

        Raises:
            ValueError: If the recipient is unknown or is the sender itself.
                The gateway records this as a tool_error, so a misaddressed
                message is a recorded attempt rather than a silent no-op.
        """
        if args.to == ctx.acting_agent_id:
            raise ValueError(f"cannot send a message to self ({args.to!r})")
        if args.to not in self._roster:
            known = ", ".join(sorted(self._roster))
            raise ValueError(f"unknown recipient {args.to!r}; known agents: {known}")

        ctx.bus.queue(PendingMessage(
            from_id=ctx.acting_agent_id,
            to_id=args.to,
            text=args.text,
            sent_round=ctx.round_number,
        ))
        return SendMessageResult(to=args.to)
