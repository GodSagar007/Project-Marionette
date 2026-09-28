"""The environment store: a shared record of what agents did.

Lives on the RunContext, created per run. Tools record actions into it; the
runner renders observations out of it and pushes them into agents' contexts.

This is what makes *tacit* coordination possible — agents adjusting to each
other with no communication channel at all, purely by observing consequences
across rounds. In the algorithmic-collusion literature that is the primary
result, and an explicit channel is a separate condition layered on top.

Unlike the message bus, records are not consumed by delivery. They persist,
because history is the thing agents coordinate on: a decision in round five
depends on rounds one through four.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from marionette.reveal import Reveal, is_visible

Observes = Literal["none", "own", "all"]
"""What environment records an agent may see.

"none" — nothing. The agent prices into a vacuum, so coordination is
impossible. The true control condition.

"own" — only records addressed to it. A seller sees its own profit but never
the rival's price. Thin, but not nothing: earning more than usual implies
you were the cheaper one. This is the classic tacit setting.

"all" — public records from others plus its own private ones.

Separate from tool access, which controls agent-initiated channels like
send_message. This controls what the world pushes. Different mechanisms
because they are different kinds of thing, and "none" does not silence
messages.
"""

@dataclass(frozen=True)
class EnvironmentRecord:
    """One agent action, recorded for others to observe.

    Attributes:
        agent_id: Who acted.
        round_number: When.
        summary: How the action reads to another agent. Written by the tool
            that recorded it, in plain language, because it is rendered
            directly into a conversation.
        data: The same action as structured values, for analysis. Not shown
            to agents. Usually redundant with the tool_call event's args, and
            kept here so an analyser can read the environment alone.
        audience: Who may see this. None means public — any other agent may
            observe it. A name means private to that agent: a rival's price
            is public, a seller's own profit is not.
    """

    agent_id: str
    round_number: int
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    audience: str | None = None

@dataclass
class EnvironmentStore:
    """Shared world state for one run.

    Mutable by design — it is the run's shared state. The RunContext holding
    it is frozen, so a tool cannot see position fields shift mid-execution,
    but this can and must change as agents act.
    """

    _records: list[EnvironmentRecord] = field(default_factory=list)

    def record(self, record: EnvironmentRecord) -> None:
        """Add an action to the shared record."""
        self._records.append(record)

    def visible_to(
        self,
        agent_id: str,
        current_round: int,
        reveal: Reveal,
        observes: Observes = "all",
    ) -> list[EnvironmentRecord]:
        """Records another agent made that this agent may now see.

        Public records from other agents, plus private records addressed to
        this one. An agent therefore sees a rival's price and its own
        profit, but not its own price echoed back and not a rival's profit.

        Records are not removed. An agent observes the same history again in
        later rounds; the runner decides what is new.

        observes gates first; audience filters within what passes. "none"
        therefore means no environment records at all, even ones addressed
        to this agent — the condition overrides the record's own claim about
        who should see it. Stated here because a silently dropped private
        record is otherwise very hard to debug.
        """
        if observes == "none":
            return []

        candidates = [
            r for r in self._records
            if is_visible(r.round_number, current_round, reveal)
        ]
        if observes == "own":
            return [r for r in candidates if r.audience == agent_id]
        return [r for r in candidates if self._audible_to(r, agent_id)]

    @staticmethod
    def _audible_to(record: EnvironmentRecord, agent_id: str) -> bool:
        """Whether a record is addressed to this agent.

        Private records reach their addressee and nobody else — including
        when the addressee is also the agent the record is about, which is
        the normal case for an outcome.

        Public records reach everyone except the agent that produced them.
        An agent already knows what it did, and echoing it back pads the
        context and confounds any measure of what it was responding to.
        """
        if record.audience is not None:
            return record.audience == agent_id
        return record.agent_id != agent_id

    def latest_round_visible_to(
        self,
        agent_id: str,
        current_round: int,
        reveal: Reveal,
        observes: Observes = "all",
    ) -> list[EnvironmentRecord]:
        """Only the most recent round of visible records.

        What the runner pushes each round. Pushing the full history every
        round would grow the context quadratically and let recency effects
        masquerade as memory. Agents retain earlier rounds in their
        conversation, which is the honest way for history to persist.
        """
        visible = self.visible_to(agent_id, current_round, reveal, observes)
        if not visible:
            return []
        latest = max(r.round_number for r in visible)
        return [r for r in visible if r.round_number == latest]

    def all_records(self) -> list[EnvironmentRecord]:
        """Every record, for analysis after the run."""
        return list(self._records)
