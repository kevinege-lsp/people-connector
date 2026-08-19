import json
from datetime import date

import pytest

from people_connector import roster
from people_connector.history import History
from people_connector.models import Cycle

CSV = """\
email,name,team,timezone,paused,avoid
Ada@Example.com,Ada Lovelace,edge,Europe/London,,grace@example.com
grace@example.com,Grace Hopper,control,America/New_York,yes,
alan@example.com,,edge,,,
"""


# -- roster --------------------------------------------------------------


def test_load_normalises_and_parses(tmp_path):
    path = tmp_path / "roster.csv"
    path.write_text(CSV)
    people = roster.load(path)

    ada, grace, alan = people
    assert ada.email == "ada@example.com"  # lowercased
    assert ada.avoid == frozenset({"grace@example.com"})
    assert grace.paused is True
    assert ada.paused is False
    assert alan.display == "alan"  # falls back to the local part


def test_blank_rows_are_skipped(tmp_path):
    path = tmp_path / "roster.csv"
    path.write_text("email,name\na@x.com,A\n,\nb@x.com,B\n")
    assert [p.email for p in roster.load(path)] == ["a@x.com", "b@x.com"]


def test_missing_file_explains_init(tmp_path):
    with pytest.raises(roster.RosterError, match="init"):
        roster.load(tmp_path / "nope.csv")


def test_bad_email_is_rejected(tmp_path):
    path = tmp_path / "roster.csv"
    path.write_text("email,name\nnot-an-email,A\n")
    with pytest.raises(roster.RosterError, match="not an email"):
        roster.load(path)


def test_avoid_pointing_at_a_stranger_is_rejected(tmp_path):
    """A typo'd avoid would silently do nothing, so it fails at load instead."""
    path = tmp_path / "roster.csv"
    path.write_text("email,avoid\na@x.com,typo@x.com\n")
    with pytest.raises(roster.RosterError, match="not in the roster"):
        roster.load(path)


def test_round_trip_preserves_everything(tmp_path):
    path = tmp_path / "roster.csv"
    path.write_text(CSV)
    original = roster.load(path)
    roster.save(path, original)
    assert roster.load(path) == original


def test_missing_optional_columns_are_fine(tmp_path):
    path = tmp_path / "roster.csv"
    path.write_text("email\na@x.com\nb@x.com\n")
    people = roster.load(path)
    assert people[0].team == "" and people[0].avoid == frozenset()


def test_init_refuses_to_clobber(tmp_path):
    path = tmp_path / "roster.csv"
    roster.init(path)
    with pytest.raises(roster.RosterError, match="already exists"):
        roster.init(path)
    roster.init(path, force=True)


def test_template_is_loadable(tmp_path):
    path = tmp_path / "roster.csv"
    roster.init(path)
    assert len(roster.load(path)) == 6


# -- history -------------------------------------------------------------


def cycle(number, groups, sat_out=(), day=5):
    return Cycle(number, date(2026, 1, day), 1, tuple(groups), tuple(sat_out))


def test_trio_counts_as_three_meetings():
    history = History([cycle(1, [("a", "b", "c")])])
    assert history.times_met("a", "b") == 1
    assert history.times_met("b", "c") == 1
    assert history.times_met("a", "c") == 1
    assert history.meeting_count("a") == 1
    assert history.partners("a") == {"b", "c"}


def test_last_met_tracks_the_most_recent_cycle():
    history = History([cycle(1, [("a", "b")]), cycle(4, [("a", "b")], day=26)])
    assert history.last_met_cycle("a", "b") == 4
    assert history.times_met("a", "b") == 2
    assert history.last_met_cycle("a", "zzz") is None


def test_sit_out_and_next_number():
    history = History([cycle(1, [("a", "b")], sat_out=["c"])])
    assert history.sit_out_count("c") == 1
    assert history.meeting_count("c") == 0
    assert history.next_number() == 2


def test_empty_history_is_neutral():
    history = History()
    assert history.next_number() == 1
    assert history.times_met("a", "b") == 0
    assert history.partners("a") == set()


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "history.json"
    original = History([cycle(1, [("a", "b"), ("c", "d", "e")], sat_out=["f"])], path)
    original.save()

    reloaded = History.load(path)
    assert reloaded.cycles == original.cycles
    assert reloaded.times_met("c", "e") == 1
    assert reloaded.sit_out_count("f") == 1

    payload = json.loads(path.read_text())
    assert payload["version"] == 1


def test_load_missing_file_gives_empty_history(tmp_path):
    assert History.load(tmp_path / "none.json").cycles == []


def test_pop_reindexes():
    history = History([cycle(1, [("a", "b")]), cycle(2, [("a", "b")], day=12)])
    assert history.times_met("a", "b") == 2
    history.pop()
    assert history.times_met("a", "b") == 1
    assert history.last_met_cycle("a", "b") == 1
    history.pop()
    assert history.times_met("a", "b") == 0
    with pytest.raises(IndexError):
        history.pop()


def test_has_date():
    history = History([cycle(1, [("a", "b")])])
    assert history.has_date(date(2026, 1, 5))
    assert not history.has_date(date(2026, 1, 12))
