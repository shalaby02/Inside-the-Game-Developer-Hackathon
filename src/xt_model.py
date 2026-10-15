"""Expected Threat (xT): how dangerous each event in the match was.

The pitch is split into a 12 x 8 grid of zones (see docs/data-format.md).
Each zone has a value: roughly, "how likely is a goal soon if my team has
the ball here?" An event's xT added is how much it changed that value.

Shots get xt_added = 0: a shot's danger is in shot_zone_value instead (the
value of the zone it was taken from), so goals don't swamp the totals.

How the zone values are built (hand-made, no outside data):
- Measure from the centre of the zone to the middle of the goal (100, 50).
- Sideways distance counts a bit less than distance up the pitch
  (Y_WEIGHT), so the wide zones by the byline still have some value:
  crosses and cut-backs come from there.
- Every HALF_DISTANCE units further from goal, the value halves.
- The best zone is scaled to TOP_VALUE (0.30).

That gives about 0.005 at the centre circle, 0.08 at the edge of the box
and 0.30 right in front of goal, which is the same shape as published xT
grids built from real match data.

Run:  python src/xt_model.py
Reads data/match.json and writes data/match_xt.csv.
"""

import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

COLS, ROWS = 12, 8          # zones along x (toward goal) and across y
ZONE_W, ZONE_H = 100 / COLS, 100 / ROWS
HALF_DISTANCE = 8           # value halves every 8 units further from goal
Y_WEIGHT = 0.7              # sideways distance counts 70%
TOP_VALUE = 0.30            # value of the best zone

FIELDS = [
    "event_id", "possession_id", "period", "minute", "second", "team", "player",
    "shirt_number", "type", "start_x", "start_y", "end_x", "end_y", "outcome",
    "is_assist",
]
XT_FIELDS = FIELDS + ["zone_start", "zone_end", "xt_added", "shot_zone_value",
                      "possession_seconds"]


def _build_grid():
    def raw(col, row):
        cx, cy = (col + 0.5) * ZONE_W, (row + 0.5) * ZONE_H
        distance = math.hypot(100 - cx, Y_WEIGHT * (50 - cy))
        return 0.5 ** (distance / HALF_DISTANCE)

    best = max(raw(c, r) for c in range(COLS) for r in range(ROWS))
    return [[round(TOP_VALUE * raw(c, r) / best, 4) for r in range(ROWS)]
            for c in range(COLS)]


GRID = _build_grid()  # GRID[col][row]


def zone_of(x, y):
    """(col, row) of a point. x = 100 and y = 100 fall in the last zone."""
    return min(int(x // ZONE_W), COLS - 1), min(int(y // ZONE_H), ROWS - 1)


def zone_label(x, y):
    """'c11r4' = column 11 (nearest the goal), row 4. Text rather than
    '11-4' so spreadsheets don't read it as a date."""
    col, row = zone_of(x, y)
    return f"c{col}r{row}"


def value(x, y):
    col, row = zone_of(x, y)
    return GRID[col][row]


def xt_added(e):
    """How much an event changed its team's chance of scoring soon."""
    t, outcome = e["type"], e["outcome"]
    if t in ("pass", "carry"):
        if outcome == "complete":
            return value(e["end_x"], e["end_y"]) - value(e["start_x"], e["start_y"])
        return -value(e["start_x"], e["start_y"])  # gave the ball away
    return 0.0  # shot (see shot_zone_value), tackle, interception, foul, clearance


def clock(e):
    return e["minute"] * 60 + e["second"]


def possession_seconds(events):
    """{possession_id: seconds from its first event to its shot, or to its
    last event if there was no shot}."""
    first, end, shot_taken = {}, {}, set()
    for e in events:
        pid = e["possession_id"]
        first.setdefault(pid, clock(e))
        if pid not in shot_taken:
            end[pid] = clock(e)
        if e["type"] == "shot":
            shot_taken.add(pid)
    return {pid: end[pid] - first[pid] for pid in first}


def add_xt(events):
    """Copies of the events with zone_start, zone_end, xt_added,
    shot_zone_value (the value of the zone a shot was taken from; blank for
    other types) and possession_seconds."""
    seconds = possession_seconds(events)
    rows = []
    for e in events:
        rows.append({
            **e,
            "zone_start": zone_label(e["start_x"], e["start_y"]),
            "zone_end": zone_label(e["end_x"], e["end_y"]),
            "xt_added": round(xt_added(e), 4),
            "shot_zone_value": value(e["start_x"], e["start_y"]) if e["type"] == "shot" else "",
            "possession_seconds": seconds[e["possession_id"]],
        })
    return rows


def describe(e):
    return (f"{e['minute']:>2}:{e['second']:02d}  {e['team'].replace('london_', ''):<4}  "
            f"{e['player'] + ' (' + str(e['shirt_number']) + ')':<20} {e['type']:<5} "
            f"({e['start_x']:g}, {e['start_y']:g}) -> ({e['end_x']:g}, {e['end_y']:g})  "
            f"{e['outcome'] + (', assist' if e['is_assist'] else ''):<18} {e['xt_added']:+.4f}")


def print_grid():
    print("Zone values (attacking left to right, toward the goal at x = 100):")
    print("        " + "".join(f"  c{c:<4}" for c in range(COLS)))
    for row in reversed(range(ROWS)):
        side = " (attacker's left)" if row == ROWS - 1 else (
            " (attacker's right)" if row == 0 else "")
        print(f"  r{row}  " + "".join(f"{GRID[c][row]:7.3f}" for c in range(COLS)) + side)
    print()


def main():
    match = json.loads((DATA_DIR / "match.json").read_text(encoding="utf-8"))
    rows = add_xt(match["events"])

    with open(DATA_DIR / "match_xt.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=XT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} events to data/match_xt.csv\n")
    print_grid()

    ranked = sorted(rows, key=lambda e: e["xt_added"], reverse=True)
    print("Top 10 positive events:")
    for i, e in enumerate(ranked[:10], start=1):
        print(f"  {i:>2}. {describe(e)}")
    print("\nTop 10 negative events:")
    for i, e in enumerate(reversed(ranked[-10:]), start=1):
        print(f"  {i:>2}. {describe(e)}")

    # Tempo: the fastest moves from a team's own half to a shot. (Ranking all
    # possessions would just list one-touch clearances at 0 seconds.)
    moves = {}
    for e in rows:
        moves.setdefault(e["possession_id"], []).append(e)
    counters = []
    for es in moves.values():
        shot = next((e for e in es if e["type"] == "shot"), None)
        if shot and es[0]["start_x"] < 50:
            counters.append((es[0]["possession_seconds"], es[0], shot))
    counters.sort(key=lambda c: c[0])
    print(f"\nFastest 5 possessions from own half to a shot ({len(counters)} in the match):")
    for i, (secs, e, shot) in enumerate(counters[:5], start=1):
        print(f"  {i}. {e['minute']:>2}:{e['second']:02d}  {e['team'].replace('london_', ''):<4}"
              f"  {secs:>3} s  x {e['start_x']:g} -> {shot['start_x']:g}"
              f"  {shot['player']} shot, {shot['outcome']}")

    # Story check: where do the planted moves land?
    rank = {e["event_id"]: i for i, e in enumerate(ranked, start=1)}

    def find(period, mmss, type_, team):
        m, s = (int(v) for v in mmss.split(":"))
        return next(e for e in rows if (e["period"], e["minute"], e["second"],
                                        e["type"], e["team"]) == (period, m, s, type_, team))

    print(f"\nStory check (rank out of {len(rows)} events):")
    for name, period, mmss, type_, team in [
            ("38' Merriden through ball", 1, "38:00", "pass", "london_red"),
            ("61' Quill assist", 2, "61:13", "pass", "london_blue"),
            ("67' Renwick through ball", 2, "67:01", "pass", "london_blue"),
            ("74' Brannick assist", 2, "74:21", "pass", "london_red"),
            ("89' Brannick assist", 2, "89:29", "pass", "london_red")]:
        e = find(period, mmss, type_, team)
        print(f"  {name:<26} xT {e['xt_added']:+.4f}   rank #{rank[e['event_id']]}")

if __name__ == "__main__":
    main()
