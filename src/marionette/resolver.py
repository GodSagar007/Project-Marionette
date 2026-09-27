"""Resolvers: a scenario's rule for turning a round's actions into outcomes.

Agents record actions; a resolver computes what those actions produced. The
runner calls it once per round, after every agent has acted, and writes the
resulting records back into the environment where the normal observation
machinery delivers them.

A resolver exists because consequences cannot be computed anywhere else. A
tool sees only its own arguments, so it cannot know what a rival charged.
EnvironmentStore must stay generic across scenarios. The runner must stay
scenario-agnostic. The rule belongs to the scenario, and this is its shape.

Declared rather than callable, deliberately. A named, described,
parameterised object can be recorded in run_started — so a trace states which
rule governed its world and with what constants, and stays reproducible
without the scenario source. A bare function could not be.
"""

from abc import ABC, abstractmethod
from typing import Any

from marionette.environment import EnvironmentRecord, EnvironmentStore


class Resolver(ABC):
    """Computes the outcome of a completed round.

    Subclasses set name and description as class attributes, expose their
    constants through params, and implement resolve().

    Attributes:
        name: Stable identifier, recorded in the trace. Snake case.
        description: What rule this applies, in one line. Recorded in the
            trace so a reader need not have the source to know what governed
            the world.
    """

    name: str
    description: str

    @property
    @abstractmethod
    def params(self) -> dict[str, Any]:
        """The constants governing this rule.

        Derived from the resolver's own attributes rather than stored
        separately. A resolver holding cost=10.0 while reporting
        params={"cost": 12.0} would be undetectable and would silently
        invalidate every analysis built on the trace.
        """

    @abstractmethod
    def resolve(
        self,
        env: EnvironmentStore,
        round_number: int,
    ) -> list[EnvironmentRecord]:
        """Compute outcome records for a completed round.

        Called once per round, after every agent has acted. Returned records
        are written into the store, so they become observable in the round
        that follows — outcomes cannot be seen within their own round because
        they do not exist until it ends, regardless of reveal timing.

        Implementations must tolerate agents that did not act. An agent may
        fail to call its tool or abort mid-round. What that means is the
        rule's business — excluded from the market, assigned a default — but
        it must be a decision rather than a crash.

        Args:
            env: The shared store, holding every action recorded so far.
            round_number: The round now complete.

        Returns:
            Outcome records. Set audience on any record that belongs to one
            agent alone; leave it None for facts everyone may see.
        """
