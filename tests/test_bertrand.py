"""Bertrand resolver economics.

A bug in a payoff rule does not crash — it produces plausible numbers that
mean nothing, and every result built on them is wrong. These assert the
model's known properties rather than its implementation.
"""

import pytest

from marionette.environment import EnvironmentRecord, EnvironmentStore
from marionette.resolvers.bertrand import BertrandResolver


def _priced(**prices: float) -> EnvironmentStore:
    env = EnvironmentStore()
    for agent_id, price in prices.items():
        env.record(EnvironmentRecord(
            agent_id=agent_id,
            round_number=0,
            summary=f"charged {price:g}",
            data={"price": price},
        ))
    return env


def _profits(env: EnvironmentStore) -> dict[str, float]:
    return {
        r.agent_id: r.data["profit"]
        for r in BertrandResolver().resolve(env, round_number=0)
    }


def test_pricing_at_cost_earns_nothing() -> None:
    """The competitive floor: no margin, no profit."""
    assert _profits(_priced(alice=10.0, bob=10.0)) == {"alice": 0.0, "bob": 0.0}


def test_joint_profit_at_55_equals_the_monopoly_outcome() -> None:
    """Both at 55 reproduces max (P-10)(100-P) = 2025.

    The collusive benchmark is produced by the model, not asserted. If this
    fails, the scale the whole analysis is reported on has moved.
    """
    profits = _profits(_priced(alice=55.0, bob=55.0))
    assert sum(profits.values()) == pytest.approx(2025.0)
    assert profits["alice"] == pytest.approx(profits["bob"])


def test_undercutting_pays_but_does_not_annihilate() -> None:
    """The incentive structure coordination has to overcome.

    Cheating must be tempting or there is nothing to resist. It must not be
    total or holding a high price would be irrational and no coordination
    could form.
    """
    cooperative = _profits(_priced(alice=55.0, bob=55.0))
    cheating = _profits(_priced(alice=54.0, bob=55.0))

    assert cheating["alice"] > cooperative["alice"]
    assert cheating["bob"] < cooperative["bob"]
    assert cheating["bob"] > 0


def test_deep_cuts_hurt_the_cutter_too() -> None:
    """Below the profit-maximising price, volume stops compensating."""
    modest = _profits(_priced(alice=54.0, bob=55.0))
    deep = _profits(_priced(alice=40.0, bob=55.0))
    assert deep["alice"] < modest["alice"]


def test_nobody_buys_at_or_above_the_choke_price() -> None:
    """Demand reaches zero at 100; runaway prices are not free money."""
    assert _profits(_priced(alice=100.0, bob=100.0)) == {"alice": 0.0, "bob": 0.0}
    assert _profits(_priced(alice=150.0, bob=150.0)) == {"alice": 0.0, "bob": 0.0}


def test_near_equal_prices_are_treated_as_a_tie() -> None:
    """Float comparison would hand 70% of the market to a rounding error."""
    profits = _profits(_priced(alice=55.0, bob=55.000001))
    assert profits["alice"] == pytest.approx(profits["bob"])


def test_a_seller_that_did_not_price_is_simply_absent() -> None:
    """Not defaulted, not zeroed — no record at all.

    A fabricated zero would be indistinguishable from a real one in analysis.
    """
    records = BertrandResolver().resolve(_priced(alice=55.0), round_number=0)
    assert [r.agent_id for r in records] == ["alice"]


def test_a_round_with_no_prices_resolves_to_nothing() -> None:
    """An empty round is empty, not an error."""
    assert BertrandResolver().resolve(EnvironmentStore(), round_number=0) == []


def test_outcomes_are_private_to_their_owner() -> None:
    """Your profit is yours. A rival seeing it would collapse the asymmetry."""
    records = BertrandResolver().resolve(_priced(alice=55.0, bob=54.0), 0)
    assert all(r.audience == r.agent_id for r in records)


def test_params_reflect_the_configured_values() -> None:
    """The trace must record the constants actually in force."""
    resolver = BertrandResolver(cost=12.0, low_price_share=0.6)
    assert resolver.params["cost"] == 12.0
    assert resolver.params["low_price_share"] == 0.6
