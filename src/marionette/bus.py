"""The message bus: agent-to-agent messages awaiting delivery.

Lives on the RunContext, so it is created per run and shared by every agent
in that run. Tools queue into it; the runner drains it.

Delivery timing is the bus's responsibility because it is where reveal
semantics become concrete. Under "immediate" a message is available as soon
as the next agent acts. Under "end_of_round" it is held until the round after
it was sent, so no agent can react within the round its sender acted — which
is what makes simultaneous play simultaneous.
"""

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class PendingMessage:
    """One message queued for delivery.

    Attributes:
        from_id: The sending agent.
        to_id: The receiving agent.
        text: The message body, as the sender wrote it.
        sent_round: The round during which it was sent.
    """

    from_id: str
    to_id: str
    text: str
    sent_round: int


@dataclass
class MessageBus:
    """Messages sent but not yet delivered.

    Mutable by design: it is the shared state of a run. The RunContext that
    references it is frozen, so position fields cannot shift under a tool
    mid-execution, but this can and must.
    """

    _pending: list[PendingMessage] = field(default_factory=list)

    def queue(self, message: PendingMessage) -> None:
        """Accept a message for later delivery."""
        self._pending.append(message)

    def drain_for(
        self,
        agent_id: str,
        current_round: int,
        reveal: Literal["immediate", "end_of_round"],
    ) -> list[PendingMessage]:
        """Remove and return the messages deliverable to an agent right now.

        Args:
            agent_id: The recipient about to act.
            current_round: The round now beginning for that agent.
            reveal: "immediate" delivers anything queued. "end_of_round"
                delivers only messages sent in an earlier round, so a message
                cannot reach anyone within the round it was sent.

        Returns:
            Messages in the order they were sent. Delivered messages are
            removed from the queue.
        """
        ready: list[PendingMessage] = []
        held: list[PendingMessage] = []
        for m in self._pending:
            deliverable = m.to_id == agent_id and (
                reveal == "immediate" or m.sent_round < current_round
            )
            (ready if deliverable else held).append(m)
        self._pending = held
        return ready

    def undelivered(self) -> list[PendingMessage]:
        """Messages still queued when the run ended.

        A non-empty result means messages were sent that nobody ever saw —
        usually a scenario whose final round had no round after it. Worth
        surfacing rather than silently dropping.
        """
        return list(self._pending)
