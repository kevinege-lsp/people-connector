import json

import pytest

from people_connector import roster
from people_connector.cli import main
from people_connector.history import History


@pytest.fixture
def workspace(tmp_path):
    """A ready-to-run roster and the flags pointing at it."""
    r = tmp_path / "roster.csv"
    h = tmp_path / "history.json"
    roster.init(r)
    return {
        "dir": tmp_path,
        "roster": r,
        "history": h,
        "flags": ["--roster", str(r), "--history", str(h)],
    }


def run(workspace, *args):
    return main(workspace["flags"] + list(args))


# -- roster management ---------------------------------------------------


def test_init_then_list(tmp_path, capsys):
    r = tmp_path / "roster.csv"
    assert main(["--roster", str(r), "init"]) == 0
    assert main(["--roster", str(r), "list"]) == 0
    assert "6 people shown" in capsys.readouterr().out


def test_add_pause_resume_remove(workspace, capsys):
    assert run(workspace, "add", "New@Example.com", "--name", "New Person",
               "--team", "edge") == 0
    people = roster.load(workspace["roster"])
    assert people[-1].email == "new@example.com"

    assert run(workspace, "pause", "new@example.com") == 0
    assert roster.find(roster.load(workspace["roster"]), "new@example.com").paused

    assert run(workspace, "resume", "new@example.com") == 0
    assert not roster.find(roster.load(workspace["roster"]), "new@example.com").paused

    assert run(workspace, "remove", "new@example.com") == 0
    assert len(roster.load(workspace["roster"])) == 6


def test_add_rejects_duplicates(workspace):
    assert run(workspace, "add", "ada@example.com") == 1


def test_unknown_email_is_a_clean_error(workspace, capsys):
    assert run(workspace, "pause", "ghost@example.com") == 1
    assert "not in the roster" in capsys.readouterr().err


def test_avoid_is_written_to_both_rows(workspace):
    assert run(workspace, "avoid", "ada@example.com", "grace@example.com") == 0
    people = roster.load(workspace["roster"])
    assert "grace@example.com" in roster.find(people, "ada@example.com").avoid
    assert "ada@example.com" in roster.find(people, "grace@example.com").avoid

    assert run(workspace, "avoid", "ada@example.com", "grace@example.com",
               "--clear") == 0
    people = roster.load(workspace["roster"])
    assert not roster.find(people, "ada@example.com").avoid
    assert not roster.find(people, "grace@example.com").avoid


def test_removing_someone_cleans_up_avoid_references(workspace):
    """Otherwise the next load fails validation on a dangling avoid."""
    run(workspace, "avoid", "ada@example.com", "grace@example.com")
    assert run(workspace, "remove", "grace@example.com") == 0
    people = roster.load(workspace["roster"])  # must not raise
    assert not roster.find(people, "ada@example.com").avoid


# -- run / preview -------------------------------------------------------


def test_preview_writes_nothing(workspace, capsys):
    assert run(workspace, "preview") == 0
    out = capsys.readouterr().out
    assert "People Connector" in out
    assert not workspace["history"].exists()
    assert not (workspace["dir"] / "cycles").exists()


def test_run_writes_files_and_history(workspace):
    out_dir = workspace["dir"] / "cycles"
    assert run(workspace, "run", "--date", "2026-08-24",
               "--out-dir", str(out_dir)) == 0

    for name in ("cycle-001.md", "cycle-001.slack.txt", "cycle-001.csv"):
        assert (out_dir / name).exists(), name

    payload = json.loads(workspace["history"].read_text())
    assert len(payload["cycles"]) == 1
    assert payload["cycles"][0]["date"] == "2026-08-24"
    assert len(payload["cycles"][0]["groups"]) == 3


def test_preview_predicts_exactly_what_run_produces(workspace, capsys):
    """The date-derived seed is the point of this: no surprises on Monday."""
    run(workspace, "preview", "--date", "2026-08-24")
    predicted = capsys.readouterr().out

    run(workspace, "run", "--date", "2026-08-24",
        "--out-dir", str(workspace["dir"] / "cycles"))
    actual = capsys.readouterr().out
    assert predicted == actual


def test_rerunning_the_same_date_is_refused(workspace, capsys):
    out_dir = str(workspace["dir"] / "cycles")
    assert run(workspace, "run", "--date", "2026-08-24", "--out-dir", out_dir) == 0
    assert run(workspace, "run", "--date", "2026-08-24", "--out-dir", out_dir) == 1
    assert "already exists" in capsys.readouterr().err

    assert run(workspace, "run", "--date", "2026-08-24", "--out-dir", out_dir,
               "--force") == 0


def test_run_with_no_triads_flag(workspace):
    run(workspace, "pause", "ada@example.com")  # leaves 5 active
    out_dir = str(workspace["dir"] / "cycles")
    assert run(workspace, "run", "--no-triads", "--out-dir", out_dir) == 0

    cycles = History.load(workspace["history"]).cycles
    assert len(cycles[0].sat_out) == 1
    assert all(len(g) == 2 for g in cycles[0].groups)


def test_run_fails_cleanly_when_everyone_is_paused(workspace, capsys):
    for email in ("ada", "grace", "alan", "barbara", "edsger"):
        run(workspace, "pause", f"{email}@example.com")
    assert run(workspace, "run") == 1
    assert "at least 2" in capsys.readouterr().err


# -- history / undo / stats ----------------------------------------------


def test_history_and_undo(workspace, capsys):
    out_dir = str(workspace["dir"] / "cycles")
    run(workspace, "run", "--date", "2026-08-24", "--out-dir", out_dir)
    run(workspace, "run", "--date", "2026-08-31", "--out-dir", out_dir)

    assert run(workspace, "history") == 0
    out = capsys.readouterr().out
    assert "Cycle 1" in out and "Cycle 2" in out

    assert run(workspace, "history", "--last", "1") == 0
    out = capsys.readouterr().out
    assert "Cycle 2" in out and "Cycle 1" not in out

    assert run(workspace, "undo") == 0
    assert len(History.load(workspace["history"]).cycles) == 1


def test_undo_with_no_history(workspace, capsys):
    assert run(workspace, "undo") == 1
    assert "No cycles to undo" in capsys.readouterr().err


def test_stats_reports_coverage(workspace, capsys):
    out_dir = str(workspace["dir"] / "cycles")
    run(workspace, "run", "--date", "2026-08-24", "--out-dir", out_dir)
    capsys.readouterr()

    assert run(workspace, "stats") == 0
    out = capsys.readouterr().out
    assert "Coverage:" in out
    assert "3/15" in out  # 6 people, one cycle of 3 pairs


def test_stats_for_one_person(workspace, capsys):
    out_dir = str(workspace["dir"] / "cycles")
    run(workspace, "run", "--date", "2026-08-24", "--out-dir", out_dir)
    capsys.readouterr()

    assert run(workspace, "stats", "--person", "ada@example.com") == 0
    out = capsys.readouterr().out
    assert "Distinct partners: 1" in out
    assert "Has not yet met (4)" in out
