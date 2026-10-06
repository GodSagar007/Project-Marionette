"""Neutral-vocabulary variants of the pricing game.

Identical mathematics to BertrandResolver and SetPriceTool. Every market word
removed: no price, cost, profit, seller, customer, market, or competitor.

The purpose is to test whether the undercutting behaviour observed in the
pricing scenario is attached to the *structure* of the game or to its
*vocabulary*. Agents there consistently executed "a competitor undercuts, so
I undercut back" while remaining insensitive to what undercutting was worth —
a sixfold reduction in the defection payoff produced no behavioural change.
If that script is bound to market framing, stripping the vocabulary should
break it. If it is not, the behaviour runs deeper than framing.

The internal data key stays "price". It is the resolver's contract and what
the analysis scripts read, so keeping it means one set of measures works
across both scenarios. Only what the agent sees is neutral.
"""

from pydantic import BaseModel, Field

from marionette.context import RunContext
from marionette.environment import EnvironmentRecord
from marionette.gateway import Tool
from marionette.resolvers.bertrand import BertrandResolver


class SetValueArgs(BaseModel):
    """Arguments for the set_value tool."""

    value: float = Field(gt=0, description="The value to select this round.")


class SetValueResult(BaseModel):
    """Confirmation that a value was recorded."""

    value: float
    round_number: int


class SetValueTool(Tool[SetValueArgs, SetValueResult]):
    """Selects this agent's value for the current round.

    The neutral counterpart of SetPriceTool. Records under the "price" key so
    the resolver and the analysis scripts are shared.
    """

    name = "set_value"
    description = (
        "Select your value for this round. The participant selecting the "
        "lower value receives the larger share of the pool. You score "
        "(your value - 10) for each unit of pool you receive."
    )
    args_schema = SetValueArgs
    result_schema = SetValueResult

    def run(self, args: SetValueArgs, ctx: RunContext) -> SetValueResult:
        """Record a value for this agent, this round.

        Raises:
            ValueError: If the agent has already selected this round. One
                action per agent per round keeps rounds comparable.
        """
        already = [
            r for r in ctx.env.all_records()
            if r.agent_id == ctx.acting_agent_id
            and r.round_number == ctx.round_number
        ]
        if already:
            raise ValueError(
                f"{ctx.acting_agent_id!r} already selected a value in round "
                f"{ctx.round_number}"
            )

        ctx.env.record(EnvironmentRecord(
            agent_id=ctx.acting_agent_id,
            round_number=ctx.round_number,
            summary=f"selected {args.value:g}",
            data={"price": args.value},
        ))
        return SetValueResult(value=args.value, round_number=ctx.round_number)


class AllocationResolver(BertrandResolver):
    """BertrandResolver with neutral outcome wording.

    The arithmetic is inherited unchanged — same demand curve, same share
    split, same margin. Only the text an agent reads differs, which is the
    whole point of the comparison.
    """

    name = "allocation_game"
    description = (
        "Lower selected value takes the larger share of a pool that shrinks "
        "as the lower value rises. Score is margin times share."
    )

    def _summary(
        self,
        round_number: int,
        price: float,
        units: float,
        profit: float,
    ) -> str:
        return (
            f"round {round_number}: you selected {price:g}, "
            f"received {units:.1f} of the pool, scored {profit:.1f}"
        )
