"""Core data types: the people, the tuning knobs, and a recorded cycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Person:
    email: str
    name: str = ""
    team: str = ""
    timezone: str = ""
    paused: bool = False
    avoid: frozenset[str] = frozenset()

    @property
    def display(self) -> str:
        """A name to show. Falls back to the local part of the email."""
        return self.name or self.email.split("@", 1)[0]


@dataclass(frozen=True)
class Config:
    """Edge-weight tuning. See SPEC.md for why the defaults are shaped this way.

    The units are arbitrary but relative: a fresh pair is worth 1000, so any
    penalty larger than that will not be chosen while a stranger is available.
    """

    new_pair_bonus: float = 1000.0
    repeat_penalty_base: float = 5000.0
    repeat_count_penalty: float = 200.0
    cross_team_bonus: float = 300.0
    timezone_penalty_per_hour: float = 40.0
    timezone_free_hours: float = 3.0
    jitter: float = 1.0
    allow_triads: bool = True


@dataclass(frozen=True)
class Cycle:
    number: int
    date: date
    seed: int
    groups: tuple[tuple[str, ...], ...] = ()
    sat_out: tuple[str, ...] = ()

    def to_json(self) -> dict:
        return {
            "number": self.number,
            "date": self.date.isoformat(),
            "seed": self.seed,
            "groups": [list(g) for g in self.groups],
            "sat_out": list(self.sat_out),
        }

    @classmethod
    def from_json(cls, raw: dict) -> "Cycle":
        return cls(
            number=int(raw["number"]),
            date=date.fromisoformat(raw["date"]),
            seed=int(raw.get("seed", 0)),
            groups=tuple(tuple(g) for g in raw.get("groups", ())),
            sat_out=tuple(raw.get("sat_out", ())),
        )


@dataclass(frozen=True)
class MatchResult:
    groups: tuple[tuple[str, ...], ...]
    sat_out: tuple[str, ...] = ()

    @property
    def pairs(self) -> tuple[tuple[str, ...], ...]:
        return tuple(g for g in self.groups if len(g) == 2)

    @property
    def trios(self) -> tuple[tuple[str, ...], ...]:
        return tuple(g for g in self.groups if len(g) == 3)
