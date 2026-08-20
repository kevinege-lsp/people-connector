"""Turning a cycle into something a human can paste somewhere."""

from __future__ import annotations

import csv
import io

from .models import Cycle, MatchResult, Person

BLURB = (
    "Find 25 minutes together this week for a casual chat. No agenda — that's "
    "the point. Whoever's name comes first sends the invite."
)


def _lookup(people: list[Person]) -> dict[str, Person]:
    return {p.email: p for p in people}


def _label(person: Person | None, email: str) -> str:
    return person.display if person else email


def _team_of(person: Person | None) -> str:
    return person.team if person and person.team else "—"


def _counts(result: MatchResult) -> str:
    bits = []
    pairs, trios = len(result.pairs), len(result.trios)
    if pairs:
        bits.append(f"{pairs} pair{'s' if pairs != 1 else ''}")
    if trios:
        bits.append(f"{trios} trio{'s' if trios != 1 else ''}")
    return " and ".join(bits) if bits else "no matches"


def _people_count(result: MatchResult) -> int:
    return sum(len(g) for g in result.groups)


def _long_date(when) -> str:
    # Built by hand rather than with %-d, which is not portable off glibc/BSD.
    return f"{when:%B} {when.day}, {when.year}"


def _short_date(when) -> str:
    return f"{when:%B} {when.day}"


def markdown(cycle: Cycle, result: MatchResult, people: list[Person]) -> str:
    index = _lookup(people)
    out = [
        f"# People Connector — Cycle {cycle.number}",
        "",
        f"Week of {_long_date(cycle.date)} · {_people_count(result)} people · "
        f"{_counts(result)}",
        "",
        BLURB,
        "",
        "| Match | Teams |",
        "| --- | --- |",
    ]

    for group in result.groups:
        members = [index.get(e) for e in group]
        names = " ↔ ".join(
            f"**{_label(m, e)}**" for m, e in zip(members, group)
        )
        teams = " ↔ ".join(_team_of(m) for m in members)
        out.append(f"| {names} | {teams} |")

    if result.sat_out:
        sitting = ", ".join(_label(index.get(e), e) for e in result.sat_out)
        out += ["", f"_Sitting out this cycle: {sitting}. Back in the pool next week._"]

    return "\n".join(out) + "\n"


def slack(cycle: Cycle, result: MatchResult, people: list[Person]) -> str:
    """Plain text. Slack renders Markdown tables badly, so this is the one you
    actually paste into the channel."""
    index = _lookup(people)
    out = [
        f":coffee: *People Connector — Cycle {cycle.number}* "
        f"(week of {_short_date(cycle.date)})",
        "",
        f"{_people_count(result)} people, {_counts(result)}. {BLURB}",
        "",
    ]

    for group in result.groups:
        names = " ↔ ".join(_label(index.get(e), e) for e in group)
        prefix = "• Trio: " if len(group) == 3 else "• "
        out.append(f"{prefix}{names}")

    if result.sat_out:
        sitting = ", ".join(_label(index.get(e), e) for e in result.sat_out)
        out += ["", f"_Sitting out this cycle: {sitting}._"]

    return "\n".join(out) + "\n"


def csv_rows(cycle: Cycle, result: MatchResult, people: list[Person]) -> str:
    """One row per person, so it sorts and filters in a spreadsheet."""
    index = _lookup(people)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["cycle", "date", "email", "name", "team", "partners", "group_size"])

    for group in result.groups:
        for email in group:
            person = index.get(email)
            others = "; ".join(
                _label(index.get(o), o) for o in group if o != email
            )
            writer.writerow(
                [
                    cycle.number,
                    cycle.date.isoformat(),
                    email,
                    _label(person, email),
                    person.team if person else "",
                    others,
                    len(group),
                ]
            )

    for email in result.sat_out:
        person = index.get(email)
        writer.writerow(
            [
                cycle.number,
                cycle.date.isoformat(),
                email,
                _label(person, email),
                person.team if person else "",
                "",
                0,
            ]
        )

    return buffer.getvalue()
