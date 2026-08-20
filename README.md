# people-connector

Weekly 1:1 coffee-chat matching for the extended Akamai Functions platform team.

In a shared office, people meet at the coffee machine. Spread across orgs,
offices, and timezones, they don't — and end up shipping into the same codebase
for a year without ever having had a conversation. This pairs everyone up each
week with someone they haven't met and asks them to find 25 minutes to talk
about nothing in particular. Scheduling is up to the two people.

The matching is deliberately not random. It's a maximum-weight perfect matching
that avoids repeats, prefers cross-team pairings, and keeps timezone gaps
workable. See [SPEC.md](SPEC.md) for the design and the reasoning behind the
weights.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Requires Python 3.10+. `networkx` is the only dependency, at install time as
well as runtime — there is no build step and nothing to `pip install -e`, so
the tool works on a box that can't reach PyPI once the venv exists.

Run it with the `./people-connector` wrapper, which puts the repo on
`PYTHONPATH` and uses `.venv` if it's there. `python -m people_connector` from
the repo root does the same thing.

## Quick start

```bash
./people-connector init          # writes a starter roster.csv
$EDITOR roster.csv               # put your people in it
./people-connector preview       # see this week's matches, write nothing
./people-connector run           # commit them, write the output files
```

Roster and history paths are relative to your working directory, so `cd` to
wherever `roster.csv` lives before running — it does not have to be this repo.

`run` prints the pairings and writes three files to `cycles/`:

| file                   | for                                        |
|------------------------|--------------------------------------------|
| `cycle-001.slack.txt`  | pasting into Slack — this is the usual one |
| `cycle-001.md`         | a wiki page or a PR                        |
| `cycle-001.csv`        | a spreadsheet                              |

## The roster

`roster.csv` is the source of truth. Edit it in your editor, in Sheets, or
through the CLI — it's a plain CSV either way, so changes review cleanly in a PR.

```csv
email,name,team,timezone,paused,avoid
ada@akamai.com,Ada Lovelace,edge-runtime,Europe/London,,
grace@akamai.com,Grace Hopper,control-plane,America/New_York,yes,
```

Only `email` is required.

- **`team`** earns a bonus for pairing across teams. It's a nudge, not a rule —
  same-team pairs still happen, which is the point.
- **`timezone`** (IANA name) keeps pairs roughly workable. Up to 3 hours apart
  is free; beyond that it costs a little. `--timezone-penalty-per-hour 0` turns
  it off.
- **`paused`** takes someone out of the pool — vacation, leave, or just not
  interested. Opting out is a first-class action, not an exception.
- **`avoid`** is a hard never-match, `;`-separated. For "that's my manager" or
  "we already talk daily", not for preferences.

```bash
./people-connector add rae@akamai.com --name "Rae Chen" --team sdk --timezone Asia/Tokyo
./people-connector pause ada@akamai.com
./people-connector resume ada@akamai.com
./people-connector avoid ada@akamai.com grace@akamai.com   # mutual
./people-connector list --all
```

## Running it weekly

```cron
0 9 * * MON  cd ~/people-connector && ./people-connector run
```

Then paste `cycles/cycle-NNN.slack.txt` into the channel. Delivery is manual on
purpose: it keeps the app credential-free, and a human glancing at the list each
week catches roster problems that no amount of validation would.

The seed is derived from the cycle date, so `preview` shows exactly what `run`
will produce, and a cron that fires twice on the same day is harmless — `run`
refuses a duplicate date unless you pass `--force`.

Made a mess? `./people-connector undo` drops the most recent cycle from
`history.json` so you can regenerate it.

## How it's going

```bash
./people-connector stats
```

```
Cycles run:  8
Active:      24 people
Coverage:    96/276 possible pairs have met (35%)
             ~15 more cycles at the current rate
```

Coverage is the number this exists to move. `./people-connector stats --person ada@akamai.com`
shows who one person still hasn't met — useful for someone who joined late and
is behind.

## Odd numbers

With an odd roster, one person is absorbed into an existing pair to make a trio.
Pass `--no-triads` to sit someone out instead; the app picks whoever has sat out
least, so the cost rotates rather than landing on the same person every time.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

The suite pins the behavior that matters: no pair repeats while strangers
remain, `avoid` is never violated even after saturation, cross-team never
outweighs a fresh pairing, and a 60-person roster stays repeat-free for 10
cycles.
