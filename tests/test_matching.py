from datetime import date

import pytest

from conftest import all_pairs, person, run_cycles
from people_connector.history import History
from people_connector.matching import MatchError, make_matches, seed_for_date
from people_connector.models import Config, Cycle


def emails_in(result):
    return sorted(e for group in result.groups for e in group)


# -- basic shape ---------------------------------------------------------


def test_everyone_is_matched_exactly_once(people):
    result = make_matches(people, History(), 1, seed=7)
    assert emails_in(result) == sorted(p.email for p in people)
    assert result.sat_out == ()
    assert all(len(g) == 2 for g in result.groups)


def test_two_people_make_one_pair():
    pool = [person("a@x.com"), person("b@x.com")]
    result = make_matches(pool, History(), 1, seed=1)
    assert result.groups == (("a@x.com", "b@x.com"),)


def test_fewer_than_two_active_people_is_an_error():
    pool = [person("a@x.com"), person("b@x.com", paused=True)]
    with pytest.raises(MatchError, match="at least 2"):
        make_matches(pool, History(), 1, seed=1)


def test_paused_people_are_excluded(people):
    people[0] = person(people[0].email, team=people[0].team, paused=True)
    result = make_matches(people, History(), 1, seed=7)
    assert people[0].email not in emails_in(result)
    assert len(emails_in(result)) == 5  # one trio absorbs the odd person out


# -- odd rosters ---------------------------------------------------------


def test_odd_roster_forms_one_trio(people):
    pool = people[:5]
    result = make_matches(pool, History(), 1, seed=7)
    assert len(result.trios) == 1
    assert len(result.pairs) == 1
    assert emails_in(result) == sorted(p.email for p in pool)
    assert result.sat_out == ()


def test_no_triads_sits_one_person_out(people):
    pool = people[:5]
    cfg = Config(allow_triads=False)
    result = make_matches(pool, History(), 1, seed=7, cfg=cfg)
    assert len(result.sat_out) == 1
    assert len(result.pairs) == 2
    assert not result.trios


def test_sit_out_rotates_to_whoever_has_sat_out_least(people):
    pool = people[:5]
    cfg = Config(allow_triads=False)
    history = run_cycles(pool, 4, cfg=cfg)
    # Over four cycles nobody should absorb the cost twice while others have
    # never sat out.
    counts = [history.sit_out_count(p.email) for p in pool]
    assert max(counts) - min(counts) <= 1


# -- the core guarantee: don't repeat while strangers remain -------------


def test_no_repeat_pairing_while_strangers_remain(people):
    """With 6 people, a round-robin needs 5 cycles to exhaust all 15 pairs.
    Across the first 5 cycles no pair should ever recur."""
    history = run_cycles(people, 5)
    seen = set()
    for cycle in history.cycles:
        pairs = all_pairs(cycle.groups)
        assert not (pairs & seen), f"cycle {cycle.number} repeated a pairing"
        seen |= pairs
    assert len(seen) == 15  # every possible pair, exactly once


def test_repeats_are_allowed_once_everyone_has_met(people):
    """After saturation the graph has no fresh edges left; the run must still
    produce a full matching rather than failing or stranding people."""
    history = run_cycles(people, 5)
    result = make_matches(people, history, 6, seed=99)
    assert emails_in(result) == sorted(p.email for p in people)


def test_recent_partners_are_avoided_before_distant_ones():
    """Given only stale options, prefer the one met longest ago.

    `x` avoids `a`, so `a` is forced to choose between the person met last
    cycle and the person met five cycles ago.
    """
    a = person("a@x.com")
    recent = person("r@x.com")
    distant = person("d@x.com")
    x = person("x@x.com", avoid={"a@x.com"})
    pool = [a, recent, distant, x]

    history = History(
        [
            Cycle(1, date(2026, 1, 5), 1, ((a.email, distant.email),)),
            Cycle(5, date(2026, 2, 2), 1, ((a.email, recent.email),)),
        ]
    )

    result = make_matches(pool, history, 6, seed=3)
    partner = next(
        other for g in result.groups if a.email in g for other in g if other != a.email
    )
    assert partner == distant.email


# -- soft preferences ----------------------------------------------------


def test_cross_team_is_preferred_when_all_else_is_equal():
    """Four people, two teams. The cross-team matching is strictly better."""
    pool = [
        person("a@x.com", team="edge"),
        person("b@x.com", team="edge"),
        person("c@x.com", team="control"),
        person("d@x.com", team="control"),
    ]
    result = make_matches(pool, History(), 1, seed=5)
    for group in result.groups:
        members = [p for p in pool if p.email in group]
        assert members[0].team != members[1].team


def test_cross_team_bonus_never_outweighs_a_fresh_pairing():
    """A same-team stranger beats a cross-team repeat."""
    pool = [
        person("a@x.com", team="edge"),
        person("b@x.com", team="edge"),
        person("c@x.com", team="control"),
        person("d@x.com", team="control"),
    ]
    # a already met c and d (both cross-team); b is the only stranger left.
    history = History(
        [
            Cycle(1, date(2026, 1, 5), 1,
                  (("a@x.com", "c@x.com"), ("b@x.com", "d@x.com"))),
            Cycle(2, date(2026, 1, 12), 1,
                  (("a@x.com", "d@x.com"), ("b@x.com", "c@x.com"))),
        ]
    )
    result = make_matches(pool, history, 3, seed=5)
    assert ("a@x.com", "b@x.com") in result.groups


def test_timezone_penalty_prefers_workable_pairings():
    """Two London and two Sydney people, none of whom have met. The matcher
    should pair within region rather than across an 9+ hour gap."""
    pool = [
        person("a@x.com", timezone="Europe/London"),
        person("b@x.com", timezone="Europe/London"),
        person("c@x.com", timezone="Australia/Sydney"),
        person("d@x.com", timezone="Australia/Sydney"),
    ]
    result = make_matches(pool, History(), 1, seed=5)
    assert ("a@x.com", "b@x.com") in result.groups
    assert ("c@x.com", "d@x.com") in result.groups


def test_timezone_penalty_can_be_disabled():
    pool = [
        person("a@x.com", timezone="Europe/London", team="edge"),
        person("b@x.com", timezone="Europe/London", team="edge"),
        person("c@x.com", timezone="Australia/Sydney", team="control"),
        person("d@x.com", timezone="Australia/Sydney", team="control"),
    ]
    cfg = Config(timezone_penalty_per_hour=0.0)
    result = make_matches(pool, History(), 1, seed=5, cfg=cfg)
    # With timezones ignored, the cross-team bonus takes over.
    for group in result.groups:
        members = [p for p in pool if p.email in group]
        assert members[0].team != members[1].team


def test_unknown_timezone_is_ignored_not_fatal():
    pool = [
        person("a@x.com", timezone="Mars/Olympus"),
        person("b@x.com", timezone="Europe/London"),
    ]
    result = make_matches(pool, History(), 1, seed=1)
    assert result.groups == (("a@x.com", "b@x.com"),)


# -- hard constraints ----------------------------------------------------


def test_avoid_is_never_violated(people):
    """Eight cycles takes six people well past saturation, so the matcher is
    forced to reuse pairings — the avoid must still hold."""
    pool = list(people)
    pool[0] = person(pool[0].email, team=pool[0].team, avoid={pool[1].email})
    banned = {pool[0].email, pool[1].email}

    history = run_cycles(pool, 8)
    assert len(history.cycles) == 8
    for cycle in history.cycles:
        for group in cycle.groups:
            assert not banned <= set(group)


def test_avoid_is_symmetric_even_if_only_one_side_declares_it():
    pool = [
        person("a@x.com"),
        person("b@x.com", avoid={"a@x.com"}),
        person("c@x.com"),
        person("d@x.com"),
    ]
    for cycle_number in range(1, 6):
        result = make_matches(pool, History(), cycle_number, seed=cycle_number)
        for group in result.groups:
            assert not {"a@x.com", "b@x.com"} <= set(group)


def test_person_who_avoids_everyone_sits_out():
    pool = [
        person("lonely@x.com", avoid={"a@x.com", "b@x.com"}),
        person("a@x.com"),
        person("b@x.com"),
    ]
    result = make_matches(pool, History(), 1, seed=1)
    assert result.sat_out == ("lonely@x.com",)
    assert result.groups == (("a@x.com", "b@x.com"),)


# -- determinism ---------------------------------------------------------


def test_same_seed_gives_the_same_matching(people):
    first = make_matches(people, History(), 1, seed=42)
    second = make_matches(people, History(), 1, seed=42)
    assert first.groups == second.groups


def test_different_seeds_can_differ(people):
    """Jitter should actually break ties differently across seeds."""
    results = {make_matches(people, History(), 1, seed=s).groups for s in range(30)}
    assert len(results) > 1


def test_seed_is_stable_for_a_date():
    from datetime import date

    assert seed_for_date(date(2026, 8, 24)) == seed_for_date(date(2026, 8, 24))
    assert seed_for_date(date(2026, 8, 24)) != seed_for_date(date(2026, 8, 31))


# -- scale ---------------------------------------------------------------


def test_a_realistic_roster_matches_quickly_and_covers_ground():
    """60 people across 6 teams, 10 cycles. Nobody should repeat, and coverage
    should climb steadily."""
    teams = ["edge", "control", "obs", "api", "sdk", "infra"]
    pool = [person(f"u{i}@x.com", team=teams[i % 6]) for i in range(60)]

    history = run_cycles(pool, 10)
    seen = set()
    for cycle in history.cycles:
        pairs = all_pairs(cycle.groups)
        assert len(pairs) == 30
        assert not (pairs & seen)
        seen |= pairs

    assert len(seen) == 300  # 10 cycles x 30 pairs, all distinct
    for p in pool:
        assert history.meeting_count(p.email) == 10
