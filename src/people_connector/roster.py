"""Reading and writing roster.csv.

The roster is a plain CSV so it stays diffable, reviewable in a PR, and openable
in Sheets. Rows are kept in file order on rewrite so CLI edits produce small
diffs.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .models import Person

COLUMNS = ["email", "name", "team", "timezone", "paused", "avoid"]

TRUTHY = {"y", "yes", "true", "t", "1", "x", "paused"}

TEMPLATE = """\
email,name,team,timezone,paused,avoid
ada@example.com,Ada Lovelace,edge-runtime,Europe/London,,
grace@example.com,Grace Hopper,control-plane,America/New_York,,
alan@example.com,Alan Turing,edge-runtime,Europe/London,,
barbara@example.com,Barbara Liskov,observability,America/Los_Angeles,,
edsger@example.com,Edsger Dijkstra,control-plane,Europe/Amsterdam,,
radia@example.com,Radia Perlman,observability,America/New_York,,
"""


class RosterError(Exception):
    pass


def _truthy(value: str) -> bool:
    return value.strip().lower() in TRUTHY


def _split_avoid(value: str) -> frozenset[str]:
    return frozenset(
        item.strip().lower() for item in value.replace(",", ";").split(";") if item.strip()
    )


def load(path: Path) -> list[Person]:
    """Read the roster. Later duplicate rows for an email win, matching CSV
    intuition that the last edit is the current one."""
    if not path.exists():
        raise RosterError(
            f"No roster at {path}. Run `people-connector init` to create one."
        )

    people: dict[str, Person] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "email" not in [
            (f or "").strip().lower() for f in reader.fieldnames
        ]:
            raise RosterError(f"{path} needs a header row with an `email` column.")

        for lineno, row in enumerate(reader, start=2):
            cleaned = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            email = cleaned.get("email", "").lower()
            if not email:
                continue  # blank spacer rows are fine
            if "@" not in email:
                raise RosterError(f"{path}:{lineno}: `{email}` is not an email address.")
            people[email] = Person(
                email=email,
                name=cleaned.get("name", ""),
                team=cleaned.get("team", ""),
                timezone=cleaned.get("timezone", ""),
                paused=_truthy(cleaned.get("paused", "")),
                avoid=_split_avoid(cleaned.get("avoid", "")),
            )

    _check_avoid_targets(people)
    return list(people.values())


def _check_avoid_targets(people: dict[str, Person]) -> None:
    """An avoid pointing at nobody is almost always a typo, and it fails silently
    at match time, so catch it at load."""
    for person in people.values():
        for target in sorted(person.avoid):
            if target not in people:
                raise RosterError(
                    f"{person.email} avoids `{target}`, who is not in the roster."
                )


def save(path: Path, people: list[Person]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for person in people:
            writer.writerow(
                {
                    "email": person.email,
                    "name": person.name,
                    "team": person.team,
                    "timezone": person.timezone,
                    "paused": "yes" if person.paused else "",
                    "avoid": ";".join(sorted(person.avoid)),
                }
            )


def init(path: Path, force: bool = False) -> None:
    if path.exists() and not force:
        raise RosterError(f"{path} already exists. Pass --force to overwrite it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE, encoding="utf-8")


def find(people: list[Person], email: str) -> Person:
    email = email.strip().lower()
    for person in people:
        if person.email == email:
            return person
    raise RosterError(f"{email} is not in the roster.")


def replace(people: list[Person], updated: Person) -> list[Person]:
    """Swap one person in place, preserving row order."""
    return [updated if p.email == updated.email else p for p in people]


def active(people: list[Person]) -> list[Person]:
    return [p for p in people if not p.paused]
