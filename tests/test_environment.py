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


def test_observes_none_sees_nothing() -> None:
    """The true control: coordination is impossible without information."""
    seen = _store().visible_to(
        "alice", current_round=1, reveal="end_of_round", observes="none"
    )
    assert seen == []


def test_observes_none_overrides_a_record_addressed_to_the_agent() -> None:
    """The condition wins over the record's own claim about its audience.

    Documented precedence rather than emergent behaviour — a silently
    dropped private record is very hard to debug.
    """
    env = _store()
    assert any(r.audience == "alice" for r in env.all_records())
    seen = env.visible_to(
        "alice", current_round=1, reveal="end_of_round", observes="none"
    )
    assert seen == []


def test_observes_own_sees_its_outcome_but_not_the_rival_price() -> None:
    """The classic tacit setting: thin information, not none.

    A seller learns its own profit and must infer the rest — earning more
    than usual implies it was the cheaper one.
    """
    seen = _store().visible_to(
        "alice", current_round=1, reveal="end_of_round", observes="own"
    )
    assert {r.summary for r in seen} == {"earned 0"}


def test_observes_own_still_hides_the_rival_outcome() -> None:
    """Narrowing what an agent sees must not widen it."""
    seen = _store().visible_to(
        "bob", current_round=1, reveal="end_of_round", observes="own"
    )
    assert all(r.summary != "earned 0" for r in seen)
    assert {r.summary for r in seen} == {"earned 7500"}


def test_observes_all_is_the_default() -> None:
    """Omitting the argument must not change behaviour."""
    env = _store()
    explicit = env.visible_to("alice", 1, "end_of_round", observes="all")
    default = env.visible_to("alice", 1, "end_of_round")
    assert {r.summary for r in explicit} == {r.summary for r in default}


def test_the_four_conditions_are_strictly_nested() -> None:
    """none < own < all, in information terms.

    If this fails the conditions are not comparable, and any effect measured
    between them could be an artifact of the gate rather than the treatment.
    """
    env = _store()
    none = env.visible_to("alice", 1, "end_of_round", observes="none")
    own = env.visible_to("alice", 1, "end_of_round", observes="own")
    every = env.visible_to("alice", 1, "end_of_round", observes="all")

    assert len(none) < len(own) < len(every)
    assert {r.summary for r in own} <= {r.summary for r in every}
