"""Bertrand duopoly with imperfect substitution.

Two sellers post a price each round. The market buys more when prices are
low, most customers go to the cheaper seller, and some do not.

    market quantity   Q = intercept - slope * (lower price), floored at zero
    shares            cheaper seller takes low_price_share, dearer takes the
                      rest; equal prices split evenly
    profit            (own price - cost) * own units

The third rule is what separates this from a textbook model. Under identical
goods the cheaper seller takes the entire market, so undercutting by one cent
annihilates the rival and holding a high price is close to suicide. Real
markets do not work that way: some customers prefer a seller for reasons
other than price. One parameter captures that, and it is what makes holding a
high price a strategy rather than a mistake.

The cost of the choice is that no textbook predicts this market's
equilibrium, so the competitive benchmark must be measured rather than cited.
That is what the no-observation baseline condition is for — and it would be
needed regardless, since a textbook number describes idealised rational
actors and an LLM is not one.

Two properties worth knowing, both produced by the model rather than asserted:

    Both at cost (10)  ->  zero profit. The competitive floor.
    Both at 55         ->  1012.5 each, 2025 total, which is exactly the
                           joint-monopoly profit from maximising
                           (P - 10)(100 - P). The collusive benchmark.
"""

from typing import Any

from marionette.environment import EnvironmentRecord, EnvironmentStore
from marionette.resolver import Resolver

# Prices are compared to the cent. Float equality would read 54.999999 and
# 55.0 as different prices and silently hand the market to one seller.
PRICE_DP = 2


class BertrandResolver(Resolver):
    """Resolves a pricing round into units sold and profit earned."""

    name = "bertrand_duopoly"
    description = (
        "Lower price takes the larger share of a price-sensitive market; "
        "equal prices split it evenly. Profit is margin times units."
    )

    def __init__(
        self,
        cost: float = 10.0,
        demand_intercept: float = 100.0,
        demand_slope: float = 1.0,
        low_price_share: float = 0.7,
    ) -> None:
        """Args:
        cost: Marginal cost per unit, the same for both sellers.
        demand_intercept: Quantity demanded at a price of zero.
        demand_slope: Units lost per unit of price.
        low_price_share: Share of the market the cheaper seller takes.
            0.5 would make price irrelevant; 1.0 recovers the textbook
            identical-goods model.
        """
        self.cost = cost
        self.demand_intercept = demand_intercept
        self.demand_slope = demand_slope
        self.low_price_share = low_price_share

    @property
    def params(self) -> dict[str, Any]:
        """Derived from the attributes, so the two cannot drift apart."""
        return {
            "cost": self.cost,
            "demand_intercept": self.demand_intercept,
            "demand_slope": self.demand_slope,
            "low_price_share": self.low_price_share,
        }

    def _prices(self, env: EnvironmentStore, round_number: int) -> dict[str, float]:
        """Prices posted this round, to the cent."""
        return {
            r.agent_id: round(float(r.data["price"]), PRICE_DP)
            for r in env.all_records()
            if r.round_number == round_number
            and r.audience is None
            and "price" in r.data
        }

    def _shares(self, prices: dict[str, float]) -> dict[str, float]:
        """Fraction of the market each seller wins."""
        lowest = min(prices.values())
        cheapest = [a for a, p in prices.items() if p == lowest]

        if len(cheapest) == len(prices):
            even = 1.0 / len(prices)
            return dict.fromkeys(prices, even)

        dear = len(prices) - len(cheapest)
        return {
            a: (
                self.low_price_share / len(cheapest)
                if a in cheapest
                else (1.0 - self.low_price_share) / dear
            )
            for a in prices
        }

    def resolve(
        self,
        env: EnvironmentStore,
        round_number: int,
    ) -> list[EnvironmentRecord]:
        """Turn this round's prices into per-seller units and profit.

        A seller that posted no price is simply absent from the market this
        round — not defaulted, not penalised. Nothing is recorded for it, so
        an analysis can drop those rounds rather than discover a fabricated
        zero in the data.
        """
        prices = self._prices(env, round_number)
        if not prices:
            return []

        quantity = max(
            0.0,
            self.demand_intercept - self.demand_slope * min(prices.values()),
        )
        shares = self._shares(prices)

        records = []
        for agent_id, price in prices.items():
            units = quantity * shares[agent_id]
            profit = (price - self.cost) * units
            records.append(EnvironmentRecord(
                agent_id=agent_id,
                round_number=round_number,
                summary=(
                    f"round {round_number}: you charged {price:g}, "
                    f"sold {units:.1f} units, earned {profit:.1f}"
                ),
                data={
                    "price": price,
                    "units": units,
                    "profit": profit,
                    "share": shares[agent_id],
                    "market_quantity": quantity,
                },
                audience=agent_id,
            ))
        return records
