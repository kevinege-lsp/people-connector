# people-connector — Spec

Weekly 1:1 coffee-chat matching for the extended Akamai Functions platform team.

## Problem

A group of teams works on one platform but sits in different orgs, offices, and
timezones. In a shared office people meet at the coffee machine; distributed,
they don't. The result is that people ship into the same codebase for a year
without ever having had a conversation.

## Goal

Every cycle (weekly to start), pair everyone in the roster with someone they
haven't met, and ask them to find 25 minutes for a chat with no agenda.
Scheduling is left to the two people — the app's only job is to produce good
pairings and a message you can paste into Slack.

Success looks like: after ~N/2 cycles, most people have met most people, and
nobody has been paired with the same person twice while strangers remained.

## Non-goals

- Sending the invitations. The app prints a list; a human posts it.
- Calendar integration or scheduling. People book their own time.
- Attendance tracking, feedback scores, or "did you actually meet?" nudges.
- Anything resembling a performance signal. This is social, and opting out is
  a first-class action (`paused`), not an exception.

## Data

Two files, both plain-text and diffable. They live wherever you point the CLI;
by default, next to each other in the working directory.

### `roster.csv`

The source of truth for who participates. Hand-editable, reviewable in a PR,
opens in Sheets.

| column     | required | meaning                                                        |
|------------|----------|----------------------------------------------------------------|
| `email`    | yes      | Identity key. Lowercased and de-duplicated on load.             |
| `name`     | no       | Display name. Falls back to the email's local part.             |
| `team`     | no       | Used for the cross-team bonus. Free-form string.                |
| `timezone` | no       | IANA name (`Europe/London`). Used for the timezone penalty.     |
| `paused`   | no       | Truthy (`yes`/`true`/`1`/`x`) means skip this cycle.            |
| `avoid`    | no       | `;`-separated emails to never match with. Enforced both ways.   |

`avoid` is a hard constraint — it removes the edge from the graph. It's for
"this is my manager" or "we already talk every day", not for preferences.

### `history.json`

Append-only record of what the app decided. Written on every non-dry run.

```json
{
  "version": 1,
  "cycles": [
    {
      "number": 1,
      "date": "2026-08-24",
      "seed": 761234,
      "groups": [["ada@…","grace@…"], ["alan@…","edsger@…","barbara@…"]],
      "sat_out": []
    }
  ]
}
```

A group is 2 people (a pair) or 3 (a trio). Trios expand into 3 pairwise
meetings for history purposes. `undo` pops the last cycle so a bad run can be
regenerated.

## Matching algorithm

The core problem is **maximum-weight perfect matching on a general graph** —
partition the roster into pairs so the total "quality" of the pairs is highest.
Greedy pairing gets this visibly wrong: it makes excellent early choices and
then strands the last few people with each other every single week.

The correct algorithm is Edmonds' blossom algorithm. We use
`networkx.max_weight_matching(G, maxcardinality=True)`, which pairs off as many
people as possible first, then maximizes total weight among those matchings.

### Edge weights

The graph is complete over active people, minus `avoid` edges. Each edge:

```
w(a,b) =  new_pair_bonus                                    # 1000
        - repeat_penalty_base / cycles_since_they_last_met  # 5000 / gap
        - repeat_count_penalty * (times_met - 1)            # 200 each
        + cross_team_bonus         if a.team != b.team      # 300
        - timezone_penalty_per_hour * hours_beyond_free     # 40/h past 3h
        + uniform(0, jitter)                                # 1.0
```

The shape of this is deliberate:

- **Repeats decay rather than being banned.** Matching someone you met last
  cycle costs 5000 — far more than the 1000 a fresh pair earns, so it won't
  happen while any stranger is available. Ten cycles later the same repeat
  costs 500, and it becomes a reasonable choice once the group has largely
  saturated. A hard ban would make the graph infeasible the week after everyone
  has met everyone.
- **Cross-team is a nudge, not a rule.** 300 will break a tie between two
  strangers but will never justify a repeat. Same-team pairings still happen,
  which is correct — the goal is that everyone knows everyone.
- **Timezone is a soft penalty with a free band.** Up to 3 hours apart is free.
  Beyond that it costs 40/hour, so an 11-hour gap costs 320 — comparable to the
  cross-team bonus, enough to prefer a workable pairing, not enough to
  partition the group into regional cliques. Set the rate to 0 to disable.
- **Jitter breaks ties randomly** so a roster with many equivalent options
  doesn't produce the same pairing every week. It's seeded (see below), so runs
  stay reproducible.

The constants are the tuning surface. They live in one dataclass
(`models.Config`) and are exposed as flags on `run`.

### Odd rosters

With an odd number of active people, one person is left over. Two strategies:

- **Trios (default).** The leftover is absorbed into whichever existing pair
  maximizes `w(left, x) + w(left, y)`. Everyone participates; a three-way
  coffee chat is a fine outcome.
- **Sit out (`--no-triads`).** One person is chosen to skip, picked by fewest
  historical sit-outs, then fewest total meetings, then random — so the cost
  rotates fairly instead of landing on the same person.

Isolated nodes (someone whose `avoid` list excludes everyone available) fall
through to sitting out rather than failing the run.

### Determinism

The seed defaults to a hash of the cycle date, so:

- `preview` shows exactly what `run` will produce.
- Cron firing twice on the same day is harmless.
- A cycle can be reproduced from `history.json` for debugging.

`run` refuses to write a second cycle with a date that already exists unless
given `--force`.

## CLI

```
./people-connector init                        # scaffold a roster.csv
./people-connector add EMAIL --name --team --timezone
./people-connector remove EMAIL
./people-connector pause EMAIL | resume EMAIL
./people-connector avoid EMAIL OTHER           # mutual, hard constraint
./people-connector list [--all]

./people-connector preview                     # dry run, prints, writes nothing
./people-connector run [--date] [--seed] [--no-triads] [--force] [--out-dir]
./people-connector history [--last N]
./people-connector undo                        # pop the most recent cycle
./people-connector stats [--person EMAIL]      # coverage and per-person counts
```

Global: `--roster PATH`, `--history PATH`.

There is no install step and no build backend: `./people-connector` is a shell
wrapper that puts the repo root on `PYTHONPATH` and execs
`python -m people_connector`. The only dependency is `networkx`, from
`requirements.txt`. This keeps the tool deployable somewhere that cannot reach
PyPI at build time.

## Output

`run` writes three renderings of the same cycle into `cycles/`:

- `cycle-003.md` — Markdown with a table. For a wiki or a PR.
- `cycle-003.slack.txt` — plain text with bullets. Slack renders tables badly;
  this is the one you actually paste.
- `cycle-003.csv` — one row per person with their partner(s), for a spreadsheet.

`preview` prints the Slack rendering to stdout and writes nothing.

## Operating it

A weekly cron entry, run from the directory holding the roster:

```
0 9 * * MON  cd ~/people-connector && ./people-connector run
```

Then paste `cycles/cycle-NNN.slack.txt` into the channel. Delivery is manual by
design for v1 — it keeps the app credential-free, and a human glancing at the
list each week catches roster problems that no amount of validation would.

## Health check

`./people-connector stats` reports the number the whole thing exists to move: **coverage**, the
fraction of all possible pairs who have met. It also lists per-person meeting
counts, so you can spot someone who joined recently and is behind, and
`--person` shows who a given person still hasn't met.

## Possible later

- Slack delivery via a bot token, once the pairing quality is trusted.
- A `groups` column for cohorts that should be preferentially crossed
  (e.g. IC/manager, or new-hire/veteran).
- Configurable cycle length beyond weekly; the history model already stores
  dates rather than assuming a 7-day cadence.
