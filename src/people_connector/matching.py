"""Pairing people up.

This is a maximum-weight perfect matching on a general graph, solved with
Edmonds' blossom algorithm via networkx. Greedy pairing is the obvious
alternative and it fails in a very visible way: it makes good choices early and
strands the same few people with each other every week.
"""

from __future__ import annotations

import itertools
import random
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import networkx as nx

from .history import History
from .models import Config, MatchResult, Person


class MatchError(Exception):
    pass


def seed_for_date(when) -> int:
    """Derive the seed from the cycle date so a preview and the real run agree,
    and so a double-fired cron produces the same answer twice."""
    return int(when.toordinal()) * 2654435761 % (2**31)


def _offset_hours(tz: str) -> float | None:
    """Current UTC offset, DST included. Unknown zones return None, which the
    caller reads as 'no timezone signal' rather than an error."""
    if not tz:
        return None
    try:
        offset = datetime.now(ZoneInfo(tz)).utcoffset()
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None
    return offset.total_seconds() / 3600 if offset is not None else None


def pair_weight(
    a: Person,
    b: Person,
    cfg: Config,
    history: History,
    cycle_number: int,
    offsets: dict[str, float | None],
    jitter: float = 0.0,
) -> float:
    weight = cfg.new_pair_bonus

    met = history.times_met(a.email, b.email)
    if met:
        last = history.last_met_cycle(a.email, b.email) or 0
        gap = max(1, cycle_number - last)
        weight -= cfg.repeat_penalty_base / gap
        weight -= cfg.repeat_count_penalty * (met - 1)

    if a.team and b.team and a.team != b.team:
        weight += cfg.cross_team_bonus

    off_a, off_b = offsets.get(a.email), offsets.get(b.email)
    if off_a is not None and off_b is not None:
        excess = max(0.0, abs(off_a - off_b) - cfg.timezone_free_hours)
        weight -= cfg.timezone_penalty_per_hour * excess

    return weight + jitter


def build_graph(
    people: list[Person],
    cfg: Config,
    history: History,
    cycle_number: int,
    rng: random.Random,
) -> nx.Graph:
    ordered = sorted(people, key=lambda p: p.email)
    offsets = {p.email: _offset_hours(p.timezone) for p in ordered}

    graph = nx.Graph()
    graph.add_nodes_from(p.email for p in ordered)

    for a, b in itertools.combinations(ordered, 2):
        # `avoid` is a hard constraint: no edge at all, in either direction.
        if b.email in a.avoid or a.email in b.avoid:
            continue
        weight = pair_weight(
            a, b, cfg, history, cycle_number, offsets, jitter=rng.uniform(0, cfg.jitter)
        )
        graph.add_edge(a.email, b.email, weight=weight)

    return graph


def _choose_sit_out(people: list[Person], history: History, rng: random.Random) -> Person:
    """Pick who skips when trios are disabled. Fewest past sit-outs first, so
    the cost rotates instead of landing on the same person every odd week."""
    return min(
        people,
        key=lambda p: (
            history.sit_out_count(p.email),
            history.meeting_count(p.email),
            rng.random(),
        ),
    )


def _absorb(
    leftover: str, groups: list[tuple[str, ...]], graph: nx.Graph
) -> int | None:
    """Find the pair that best takes on a third member. Returns its index, or
    None if every pair contains someone the leftover avoids."""
    best_index, best_score = None, None
    for index, group in enumerate(groups):
        if len(group) != 2:
            continue
        if not all(graph.has_edge(leftover, member) for member in group):
            continue
        score = sum(graph[leftover][member]["weight"] for member in group)
        if best_score is None or score > best_score:
            best_index, best_score = index, score
    return best_index


def make_matches(
    people: list[Person],
    history: History,
    cycle_number: int,
    seed: int,
    cfg: Config | None = None,
) -> MatchResult:
    cfg = cfg or Config()
    rng = random.Random(seed)

    pool = [p for p in people if not p.paused]
    if len(pool) < 2:
        raise MatchError(
            f"Need at least 2 active people to match, found {len(pool)}. "
            "Check for paused rows in the roster."
        )

    sat_out: list[str] = []
    if len(pool) % 2 == 1 and not cfg.allow_triads:
        skipper = _choose_sit_out(pool, history, rng)
        sat_out.append(skipper.email)
        pool = [p for p in pool if p.email != skipper.email]

    graph = build_graph(pool, cfg, history, cycle_number, rng)
    matching = nx.max_weight_matching(graph, maxcardinality=True)

    groups: list[tuple[str, ...]] = [tuple(sorted(edge)) for edge in matching]
    groups.sort()

    matched = {email for edge in matching for email in edge}
    leftovers = sorted(p.email for p in pool if p.email not in matched)

    for leftover in leftovers:
        index = _absorb(leftover, groups, graph) if cfg.allow_triads else None
        if index is None:
            sat_out.append(leftover)
        else:
            groups[index] = tuple(sorted(groups[index] + (leftover,)))

    groups.sort()
    return MatchResult(groups=tuple(groups), sat_out=tuple(sorted(sat_out)))
