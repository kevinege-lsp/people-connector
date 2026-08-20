"""Command-line interface."""

from __future__ import annotations

import argparse
import dataclasses
import itertools
import sys
from datetime import date
from pathlib import Path

from . import render, roster
from .history import History
from .matching import MatchError, make_matches, seed_for_date
from .models import Config, Cycle, Person
from .roster import RosterError

DEFAULT_ROSTER = Path("roster.csv")
DEFAULT_HISTORY = Path("history.json")
DEFAULT_OUT = Path("cycles")


# -- helpers -------------------------------------------------------------


def _config(args) -> Config:
    overrides = {}
    for field in dataclasses.fields(Config):
        value = getattr(args, field.name, None)
        if value is not None:
            overrides[field.name] = value
    if getattr(args, "no_triads", False):
        overrides["allow_triads"] = False
    return dataclasses.replace(Config(), **overrides)


def _label(people: list[Person], email: str) -> str:
    for person in people:
        if person.email == email:
            return person.display
    return email


def _plural(count: int, word: str, plural: str | None = None) -> str:
    return f"{count} {word if count == 1 else (plural or word + 's')}"


# -- roster commands -----------------------------------------------------


def cmd_init(args) -> int:
    roster.init(args.roster, force=args.force)
    print(f"Wrote a starter roster to {args.roster}.")
    print("Edit it, then run `people-connector preview`.")
    return 0


def cmd_add(args) -> int:
    people = roster.load(args.roster) if args.roster.exists() else []
    email = args.email.strip().lower()
    if any(p.email == email for p in people):
        print(f"{email} is already in the roster.", file=sys.stderr)
        return 1
    people.append(
        Person(
            email=email,
            name=args.name or "",
            team=args.team or "",
            timezone=args.timezone or "",
        )
    )
    roster.save(args.roster, people)
    print(f"Added {email}. The roster now has {_plural(len(people), 'person', 'people')}.")
    return 0


def cmd_remove(args) -> int:
    people = roster.load(args.roster)
    person = roster.find(people, args.email)
    remaining = [p for p in people if p.email != person.email]
    # Drop dangling avoid references, which would fail validation on next load.
    remaining = [
        dataclasses.replace(p, avoid=p.avoid - {person.email}) for p in remaining
    ]
    roster.save(args.roster, remaining)
    print(f"Removed {person.email}. Past cycles in history.json are untouched.")
    return 0


def _set_paused(args, paused: bool) -> int:
    people = roster.load(args.roster)
    person = roster.find(people, args.email)
    roster.save(args.roster, roster.replace(people, dataclasses.replace(person, paused=paused)))
    print(f"{person.display} is now {'paused' if paused else 'active'}.")
    return 0


def cmd_pause(args) -> int:
    return _set_paused(args, True)


def cmd_resume(args) -> int:
    return _set_paused(args, False)


def cmd_avoid(args) -> int:
    people = roster.load(args.roster)
    one = roster.find(people, args.email)
    two = roster.find(people, args.other)
    if one.email == two.email:
        print("Those are the same person.", file=sys.stderr)
        return 1

    if args.clear:
        one = dataclasses.replace(one, avoid=one.avoid - {two.email})
        two = dataclasses.replace(two, avoid=two.avoid - {one.email})
        verb = "no longer avoid"
    else:
        one = dataclasses.replace(one, avoid=one.avoid | {two.email})
        two = dataclasses.replace(two, avoid=two.avoid | {one.email})
        verb = "will never be matched with"

    people = roster.replace(roster.replace(people, one), two)
    roster.save(args.roster, people)
    print(f"{one.display} {verb} {two.display}.")
    return 0


def cmd_list(args) -> int:
    people = roster.load(args.roster)
    shown = people if args.all else roster.active(people)
    if not shown:
        print("Roster is empty.")
        return 0

    width = max(len(p.email) for p in shown)
    for person in sorted(shown, key=lambda p: (p.team, p.display.lower())):
        flags = []
        if person.paused:
            flags.append("paused")
        if person.avoid:
            flags.append(f"avoids {len(person.avoid)}")
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        team = person.team or "—"
        print(f"{person.email:<{width}}  {person.display:<22} {team:<18}{suffix}")

    paused = len(people) - len(roster.active(people))
    note = f", {paused} paused" if paused and not args.all else ""
    print(f"\n{_plural(len(shown), 'person', 'people')} shown{note}.")
    return 0


# -- the main event ------------------------------------------------------


def _run(args, dry: bool) -> int:
    people = roster.load(args.roster)
    history = History.load(args.history)

    when = date.fromisoformat(args.date) if args.date else date.today()
    if not dry and history.has_date(when) and not args.force:
        print(
            f"A cycle for {when} already exists. Re-run with --force to add "
            f"another, or use `undo` to drop it first.",
            file=sys.stderr,
        )
        return 1

    number = history.next_number()
    seed = args.seed if args.seed is not None else seed_for_date(when)
    result = make_matches(people, history, number, seed, _config(args))
    cycle = Cycle(
        number=number,
        date=when,
        seed=seed,
        groups=result.groups,
        sat_out=result.sat_out,
    )

    print(render.slack(cycle, result, people))

    if dry:
        print("(preview — nothing written)", file=sys.stderr)
        return 0

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"cycle-{number:03d}"
    written = []
    for suffix, text in (
        (".md", render.markdown(cycle, result, people)),
        (".slack.txt", render.slack(cycle, result, people)),
        (".csv", render.csv_rows(cycle, result, people)),
    ):
        path = args.out_dir / f"{stem}{suffix}"
        path.write_text(text, encoding="utf-8")
        written.append(path)

    history.add(cycle)
    history.save(args.history)

    print(f"Wrote {', '.join(str(p) for p in written)}", file=sys.stderr)
    print(f"Recorded cycle {number} in {args.history}", file=sys.stderr)
    return 0


def cmd_run(args) -> int:
    return _run(args, dry=False)


def cmd_preview(args) -> int:
    return _run(args, dry=True)


# -- looking back --------------------------------------------------------


def cmd_history(args) -> int:
    people = roster.load(args.roster) if args.roster.exists() else []
    history = History.load(args.history)
    if not history.cycles:
        print("No cycles yet.")
        return 0

    cycles = history.cycles[-args.last :] if args.last else history.cycles
    for cycle in cycles:
        print(f"Cycle {cycle.number} — {cycle.date}")
        for group in cycle.groups:
            names = " ↔ ".join(_label(people, e) for e in group)
            print(f"    {names}")
        if cycle.sat_out:
            print(f"    (sat out: {', '.join(_label(people, e) for e in cycle.sat_out)})")
        print()
    return 0


def cmd_undo(args) -> int:
    history = History.load(args.history)
    try:
        cycle = history.pop()
    except IndexError:
        print("No cycles to undo.", file=sys.stderr)
        return 1
    history.save(args.history)
    print(f"Dropped cycle {cycle.number} ({cycle.date}) from {args.history}.")
    print("Generated files in cycles/ were left alone; delete them yourself.")
    return 0


def cmd_stats(args) -> int:
    people = roster.load(args.roster)
    history = History.load(args.history)
    pool = roster.active(people)

    if args.person:
        person = roster.find(people, args.person)
        met = history.partners(person.email)
        unmet = sorted(
            (p for p in pool if p.email != person.email and p.email not in met),
            key=lambda p: (p.team, p.display.lower()),
        )
        print(f"{person.display} <{person.email}>")
        print(f"  Meetings: {history.meeting_count(person.email)}")
        print(f"  Distinct partners: {len(met)}")
        print(f"  Sat out: {history.sit_out_count(person.email)}")
        if unmet:
            print(f"\n  Has not yet met ({len(unmet)}):")
            for other in unmet:
                print(f"    {other.display:<24} {other.team or '—'}")
        else:
            print("\n  Has met everyone currently active. ")
        return 0

    possible = len(pool) * (len(pool) - 1) // 2
    met_pairs = sum(
        1
        for a, b in itertools.combinations(sorted(p.email for p in pool), 2)
        if history.times_met(a, b)
    )
    coverage = (met_pairs / possible * 100) if possible else 0.0

    print(f"Cycles run:  {len(history.cycles)}")
    print(f"Active:      {_plural(len(pool), 'person', 'people')}")
    print(f"Coverage:    {met_pairs}/{possible} possible pairs have met ({coverage:.0f}%)")
    if possible and met_pairs < possible and history.cycles:
        per_cycle = met_pairs / len(history.cycles)
        if per_cycle:
            remaining = (possible - met_pairs) / per_cycle
            print(f"             ~{remaining:.0f} more cycles at the current rate")

    print("\nPer person:")
    rows = sorted(pool, key=lambda p: (-history.meeting_count(p.email), p.display.lower()))
    for person in rows:
        count = history.meeting_count(person.email)
        distinct = len(history.partners(person.email))
        print(f"  {person.display:<24} {count:>3} meetings, {distinct:>3} distinct")
    return 0


# -- wiring --------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="people-connector",
        description="Weekly 1:1 coffee-chat matching for a group of teams.",
    )
    parser.add_argument("--roster", type=Path, default=DEFAULT_ROSTER, help="roster CSV")
    parser.add_argument(
        "--history", type=Path, default=DEFAULT_HISTORY, help="history JSON"
    )
    subs = parser.add_subparsers(dest="command", required=True)

    p = subs.add_parser("init", help="write a starter roster.csv")
    p.add_argument("--force", action="store_true", help="overwrite an existing roster")
    p.set_defaults(func=cmd_init)

    p = subs.add_parser("add", help="add a person")
    p.add_argument("email")
    p.add_argument("--name")
    p.add_argument("--team")
    p.add_argument("--timezone", help="IANA name, e.g. Europe/London")
    p.set_defaults(func=cmd_add)

    p = subs.add_parser("remove", help="remove a person")
    p.add_argument("email")
    p.set_defaults(func=cmd_remove)

    p = subs.add_parser("pause", help="take someone out of the pool")
    p.add_argument("email")
    p.set_defaults(func=cmd_pause)

    p = subs.add_parser("resume", help="put someone back in the pool")
    p.add_argument("email")
    p.set_defaults(func=cmd_resume)

    p = subs.add_parser("avoid", help="never match two people (mutual)")
    p.add_argument("email")
    p.add_argument("other")
    p.add_argument("--clear", action="store_true", help="undo an avoid")
    p.set_defaults(func=cmd_avoid)

    p = subs.add_parser("list", help="show the roster")
    p.add_argument("--all", action="store_true", help="include paused people")
    p.set_defaults(func=cmd_list)

    for name, func, help_text in (
        ("run", cmd_run, "generate and record this cycle's matches"),
        ("preview", cmd_preview, "show what run would do, without writing"),
    ):
        p = subs.add_parser(name, help=help_text)
        p.add_argument("--date", help="cycle date, YYYY-MM-DD (default: today)")
        p.add_argument("--seed", type=int, help="override the date-derived seed")
        p.add_argument(
            "--no-triads",
            action="store_true",
            help="with an odd roster, sit one person out instead of making a trio",
        )
        p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
        p.add_argument("--force", action="store_true", help="allow a duplicate date")
        p.add_argument("--cross-team-bonus", type=float, dest="cross_team_bonus")
        p.add_argument("--repeat-penalty-base", type=float, dest="repeat_penalty_base")
        p.add_argument(
            "--timezone-penalty-per-hour",
            type=float,
            dest="timezone_penalty_per_hour",
            help="set to 0 to ignore timezones entirely",
        )
        p.set_defaults(func=func)

    p = subs.add_parser("history", help="show past cycles")
    p.add_argument("--last", type=int, help="only the most recent N cycles")
    p.set_defaults(func=cmd_history)

    p = subs.add_parser("undo", help="drop the most recent cycle")
    p.set_defaults(func=cmd_undo)

    p = subs.add_parser("stats", help="coverage and per-person counts")
    p.add_argument("--person", help="focus on one person, and list who they haven't met")
    p.set_defaults(func=cmd_stats)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (RosterError, MatchError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
