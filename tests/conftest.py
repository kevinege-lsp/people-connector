import itertools

import pytest

from people_connector.history import History
from people_connector.matching import make_matches
from people_connector.models import Cycle, Person


def person(email, team="", timezone="", paused=False, avoid=()):
    return Person(
        email=email,
        name=email.split("@")[0].title(),
        team=team,
        timezone=timezone,
        paused=paused,
        avoid=frozenset(avoid),
    )


@pytest.fixture
def people():
    """Six people across three teams, evenly split."""
    teams = ["edge", "control", "obs"]
    return [
        person(f"p{i}@example.com", team=teams[i % 3])
        for i in range(6)
    ]


def run_cycles(people, count, start=1, cfg=None, history=None):
    """Simulate `count` consecutive cycles, returning the history."""
    from datetime import date, timedelta

    history = history or History()
    for offset in range(count):
        number = start + offset
        result = make_matches(people, history, number, seed=1000 + number, cfg=cfg)
        history.add(
            Cycle(
                number=number,
                date=date(2026, 1, 5) + timedelta(weeks=offset),
                seed=1000 + number,
                groups=result.groups,
                sat_out=result.sat_out,
            )
        )
    return history


def all_pairs(groups):
    """Expand groups (pairs and trios) into pairwise meetings."""
    return {
        frozenset(pair)
        for group in groups
        for pair in itertools.combinations(sorted(group), 2)
    }
