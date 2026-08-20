"""The record of past cycles, and the queries the matcher asks of it.

Stored as JSON so it is diffable and hand-fixable. A "group" is 2 or 3 emails;
a trio counts as three pairwise meetings.
"""

from __future__ import annotations

import itertools
import json
from collections import Counter
from datetime import date
from pathlib import Path

from .models import Cycle

VERSION = 1

Pair = frozenset


def _key(a: str, b: str) -> Pair:
    return frozenset((a, b))


class History:
    def __init__(self, cycles: list[Cycle] | None = None, path: Path | None = None):
        self.cycles: list[Cycle] = list(cycles or [])
        self.path = path
        self._reindex()

    # -- persistence ----------------------------------------------------

    @classmethod
    def load(cls, path: Path) -> "History":
        if not path.exists():
            return cls([], path)
        raw = json.loads(path.read_text(encoding="utf-8") or "{}")
        cycles = [Cycle.from_json(c) for c in raw.get("cycles", [])]
        cycles.sort(key=lambda c: c.number)
        return cls(cycles, path)

    def save(self, path: Path | None = None) -> None:
        target = path or self.path
        if target is None:
            raise ValueError("History has no path to save to.")
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": VERSION, "cycles": [c.to_json() for c in self.cycles]}
        target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    # -- indexing -------------------------------------------------------

    def _reindex(self) -> None:
        """Precompute pair lookups. Cheap to rebuild, and the matcher hits these
        O(n^2) times per run."""
        self._last_met: dict[Pair, int] = {}
        self._times_met: Counter[Pair] = Counter()
        self._meetings: Counter[str] = Counter()
        self._sat_out: Counter[str] = Counter()
        self._partners: dict[str, set[str]] = {}

        for cycle in self.cycles:
            for group in cycle.groups:
                for a, b in itertools.combinations(sorted(group), 2):
                    key = _key(a, b)
                    self._times_met[key] += 1
                    self._last_met[key] = max(self._last_met.get(key, 0), cycle.number)
                    self._partners.setdefault(a, set()).add(b)
                    self._partners.setdefault(b, set()).add(a)
                for email in group:
                    self._meetings[email] += 1
            for email in cycle.sat_out:
                self._sat_out[email] += 1

    # -- queries --------------------------------------------------------

    def times_met(self, a: str, b: str) -> int:
        return self._times_met.get(_key(a, b), 0)

    def last_met_cycle(self, a: str, b: str) -> int | None:
        return self._last_met.get(_key(a, b))

    def meeting_count(self, email: str) -> int:
        return self._meetings.get(email, 0)

    def sit_out_count(self, email: str) -> int:
        return self._sat_out.get(email, 0)

    def partners(self, email: str) -> set[str]:
        return set(self._partners.get(email, ()))

    def next_number(self) -> int:
        return (max((c.number for c in self.cycles), default=0)) + 1

    def has_date(self, when: date) -> bool:
        return any(c.date == when for c in self.cycles)

    # -- mutation -------------------------------------------------------

    def add(self, cycle: Cycle) -> None:
        self.cycles.append(cycle)
        self.cycles.sort(key=lambda c: c.number)
        self._reindex()

    def pop(self) -> Cycle:
        if not self.cycles:
            raise IndexError("No cycles to undo.")
        cycle = self.cycles.pop()
        self._reindex()
        return cycle
