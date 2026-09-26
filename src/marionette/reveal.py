"""Reveal timing: when one agent's action becomes visible to another.

Both the message bus and the environment store answer the same question —
is something recorded in round R visible to an agent acting in round C? The
rule lives here so the two cannot drift apart.

The distinction is a research control, not a convenience. Under sequential
play an agent choosing its action can already see what the others chose this
round, so apparent coordination may be nothing more than best-response to an
observed move. Under simultaneous play nobody can react inside the round
their counterpart acted, which is the condition the collusion literature
runs.
"""

from typing import Literal

Reveal = Literal["immediate", "end_of_round"]


def is_visible(recorded_round: int, current_round: int, reveal: Reveal) -> bool:
    """Whether something recorded in one round is visible in another.

    Args:
        recorded_round: The round in which the action happened.
        current_round: The round of the agent now acting.
        reveal: "immediate" makes an action visible as soon as the next agent
            acts, including within its own round. "end_of_round" withholds it
            until the following round begins.

    Returns:
        True if the acting agent may see it.
    """
    if reveal == "immediate":
        return True
    return recorded_round < current_round
