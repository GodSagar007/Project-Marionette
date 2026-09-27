"""Environment store visibility rules.

The audience rule decides what each agent knows, and information state is
the object of study in coordination research. A bug here would not crash
anything — it would quietly produce agents that saw more or less than the
scenario intended.
"""

from marionette.environment import EnvironmentRecord, EnvironmentStore


def _store() -> EnvironmentStore:
    env = EnvironmentStore()
    env.record(EnvironmentRecord(
        agent_id="alice", round_number=0, summary="charged 90",
        data={"price": 90.0},
    ))
    env.record(EnvironmentRecord(
        agent_id="bob", round_number=0, summary="charged 85",
        data={"price": 85.0},
    ))
    env.record(EnvironmentRecord(
        agent_id="alice", round_number=0, summary="earned 0",
        data={"profit": 0.0}, audience="alice",
    ))
    env.record(EnvironmentRecord(
        agent_id="bob", round_number=0, summary="earned 7500",
        data={"profit": 7500.0}, audience="bob",
    ))
    return env


def test_agent_sees_rival_action_and_own_outcome() -> None:
    """The intended information state: their price, my profit."""
    seen = _store().visible_to("alice", current_round=0, reveal="immediate")
    assert {(r.agent_id, r.summary) for r in seen} == {
        ("bob", "charged 85"),
        ("alice", "earned 0"),
    }


def test_agent_does_not_see_rival_outcome() -> None:
    """Private records reach their addressee and nobody else."""
    seen = _store().visible_to("alice", current_round=0, reveal="immediate")
    assert all(r.summary != "earned 7500" for r in seen)


def test_agent_does_not_see_own_action_echoed_back() -> None:
    """An agent already knows what it did; echoing it pads the context."""
    seen = _store().visible_to("alice", current_round=0, reveal="immediate")
    assert all(r.summary != "charged 90" for r in seen)


def test_end_of_round_hides_the_current_round_entirely() -> None:
    """Under simultaneous play nothing from this round is visible yet."""
    seen = _store().visible_to("alice", current_round=0, reveal="end_of_round")
    assert seen == []


def test_end_of_round_reveals_once_the_round_has_passed() -> None:
    """The same records become visible from the following round."""
    seen = _store().visible_to("alice", current_round=1, reveal="end_of_round")
    assert {r.summary for r in seen} == {"charged 85", "earned 0"}


def test_records_persist_across_observations() -> None:
    """Unlike messages, observing does not consume. History is coordinated on."""
    env = _store()
    first = env.visible_to("alice", current_round=1, reveal="end_of_round")
    second = env.visible_to("alice", current_round=1, reveal="end_of_round")
    assert len(first) == len(second) == 2
    assert len(env.all_records()) == 4
