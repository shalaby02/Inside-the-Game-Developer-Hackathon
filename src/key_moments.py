"""Key moments: the 10-12 events the Narrator should talk about.

Reads data/match_xt.csv and writes data/key_moments.json. Each moment is
facts only (plain numbers, no prose), so the Narrator agent can explain
them without inventing anything.

Categories (one per moment):
- goal               every goal, always included.
- save               a saved shot from a big chance (shot_zone_value >=
                     BIG_CHANCE). Credited to the other team's goalkeeper.
- big_chance_missed  an off-target or blocked shot from a big chance.
- momentum_shift     one team creates more threat than the other in at least
                     MIN_RUN_BLOCKS 5-minute blocks in a row, after the other
                     team was on top in the block before. Threat = xt_added
                     of completed passes and carries only (see
                     docs/match-story.md). The team's threat over the run
                     must beat the other team's by MIN_SHIFT_MARGIN. Biggest
                     margin first.
- biggest_threat_swing  the completed passes and carries with the most
                     xt_added.

Selection: goals first. Then the other categories in the order above, best
candidate first, skipping a candidate if its category already has
MAX_PER_CATEGORY moments or if another moment is less than MIN_GAP_SECONDS
away in the same period.

Tags (a list, can be empty):
- counter            the moment's possession starts in the team's own half
                     (start_x < 50), ends in a shot and takes
                     MAX_COUNTER_SECONDS or less.

Facts are rounded numbers, plus action_type ("pass" or "carry") for every
moment with a key action: a threat swing's own pass or carry, or a shot's
key pass (the last pass before it). Momentum shifts have none. team_score and opponent_score are the score just
after the moment (for a momentum shift: at the start of its first block).

Run:  python src/key_moments.py
"""

import csv
import json
import math
from pathlib import Path

from xt_model import value

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

BIG_CHANCE = 0.15           # shot_zone_value: the 2 best zones (0.161 and 0.30)
MAX_COUNTER_SECONDS = 15
MIN_RUN_BLOCKS = 3          # 15 minutes on top
MIN_SHIFT_MARGIN = 0.25     # threat over the run, team minus other team
BLOCK_MINUTES = 5
MAX_PER_CATEGORY = 3
MIN_GAP_SECONDS = 60
PITCH_M = (105, 68)         # for distances in metres

PRIORITY = ["save", "big_chance_missed", "momentum_shift", "biggest_threat_swing"]
GOALKEEPERS = {"london_red": "Ellis Harwick", "london_blue": "Bram Hollis"}  # docs/teams.md
TEAMS = ("london_red", "london_blue")


def load(path):
    ints = ("event_id", "possession_id", "period", "minute", "second",
            "shirt_number", "possession_seconds")
    floats = ("start_x", "start_y", "end_x", "end_y", "xt_added")
    rows = []
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            for k in ints:
                r[k] = int(r[k])
            for k in floats:
                r[k] = float(r[k])
            r["is_assist"] = r["is_assist"] == "True"
            r["shot_zone_value"] = float(r["shot_zone_value"]) if r["shot_zone_value"] else None
            rows.append(r)
    return rows


def clock(e):
    return e["minute"] * 60 + e["second"]


def other(team):
    return TEAMS[1] if team == TEAMS[0] else TEAMS[0]


def threat(e):
    """Threat created: xt_added of completed passes and carries, else 0."""
    return e["xt_added"] if e["type"] in ("pass", "carry") and e["outcome"] == "complete" else 0.0


def distance_m(x, y):
    return math.hypot((100 - x) * PITCH_M[0] / 100, (50 - y) * PITCH_M[1] / 100)


def scores_after(events):
    """{event_id: {team: goals so far, including this event}}."""
    score, out = dict.fromkeys(TEAMS, 0), {}
    for e in events:
        if e["type"] == "shot" and e["outcome"] == "goal":
            score[e["team"]] += 1
        out[e["event_id"]] = dict(score)
    return out


def moment(category, e, team, players, facts, score, score_value, tags=()):
    return {"category": category, "tags": list(tags), "period": e["period"],
            "minute": e["minute"], "second": e["second"], "team": team, "players": players,
            "facts": {**facts, "team_score": score[team], "opponent_score": score[other(team)]},
            "_score": score_value}


def candidates(events):
    possessions = {}
    for e in events:
        possessions.setdefault(e["possession_id"], []).append(e)
    score = scores_after(events)

    # Counter-attacks (the counter tag), ranked fastest first (counter_rank).
    counters = [es for es in possessions.values()
                if es[0]["start_x"] < 50 and es[0]["possession_seconds"] <= MAX_COUNTER_SECONDS
                and any(p["type"] == "shot" for p in es)]
    counters.sort(key=lambda es: (es[0]["possession_seconds"], clock(es[0])))
    counter_rank = {es[0]["possession_id"]: i for i, es in enumerate(counters, start=1)}

    def tags(e):
        return ["counter"] if e["possession_id"] in counter_rank else []

    out = []
    for e in events:
        if e["type"] != "shot":
            continue
        es = possessions[e["possession_id"]]
        before = [p for p in es if p["event_id"] < e["event_id"]]
        key_pass = next((p for p in reversed(before) if p["type"] == "pass"), None)
        facts = {
            "shot_x": e["start_x"], "shot_y": e["start_y"],
            "shot_zone_value": e["shot_zone_value"],
            "distance_to_goal_m": round(distance_m(e["start_x"], e["start_y"]), 1),
            "possession_seconds": e["possession_seconds"],
            "possession_start_x": es[0]["start_x"],
        }
        if key_pass:
            facts["action_type"] = key_pass["type"]
            facts["key_pass_xt_added"] = key_pass["xt_added"]
        players = [e["player"]] + ([key_pass["player"]] if key_pass and key_pass["player"] != e["player"] else [])

        if e["outcome"] == "goal":
            if e["possession_id"] in counter_rank:
                facts["counter_rank"] = counter_rank[e["possession_id"]]
                facts["counters_in_match"] = len(counters)
            out.append(moment("goal", e, e["team"], players, facts, score[e["event_id"]],
                              e["shot_zone_value"], tags(e)))
        elif e["shot_zone_value"] >= BIG_CHANCE:
            if e["outcome"] == "saved":
                keeper_team = other(e["team"])
                out.append(moment("save", e, keeper_team, [GOALKEEPERS[keeper_team]] + players,
                                  facts, score[e["event_id"]], e["shot_zone_value"], tags(e)))
            else:
                out.append(moment("big_chance_missed", e, e["team"], players, facts,
                                  score[e["event_id"]], e["shot_zone_value"], tags(e)))

    out += momentum_shifts(events, score)

    for i, e in enumerate(events):
        if threat(e) <= 0:
            continue
        nxt = events[i + 1] if i + 1 < len(events) else None
        receiver = nxt["player"] if (e["type"] == "pass" and nxt and nxt["team"] == e["team"]
                                     and nxt["player"] != e["player"]) else None
        out.append(moment("biggest_threat_swing", e, e["team"],
                          [e["player"]] + ([receiver] if receiver else []), {
            "xt_added": e["xt_added"],
            "zone_start_value": value(e["start_x"], e["start_y"]),
            "zone_end_value": value(e["end_x"], e["end_y"]),
            "start_x": e["start_x"], "start_y": e["start_y"],
            "end_x": e["end_x"], "end_y": e["end_y"],
            "action_type": e["type"],
        }, score[e["event_id"]], e["xt_added"], tags(e)))
    return out


def blocks(events):
    """[(period, start_minute, [events])] in match order. First-half
    stoppage (45+) gets its own block; the second half starts again at 45."""
    out = {}
    for e in events:
        out.setdefault((e["period"], e["minute"] // BLOCK_MINUTES * BLOCK_MINUTES), []).append(e)
    return [(p, m, es) for (p, m), es in out.items()]


def momentum_shifts(events, score):
    timeline = []
    for period, start, es in blocks(events):
        t = {team: sum(threat(e) for e in es if e["team"] == team) for team in TEAMS}
        leader = max(TEAMS, key=t.get) if t[TEAMS[0]] != t[TEAMS[1]] else None
        timeline.append({"period": period, "start": start, "events": es, "threat": t,
                         "leader": leader})

    runs = []  # [first index, last index, leader]
    for i, b in enumerate(timeline):
        if runs and runs[-1][2] == b["leader"]:
            runs[-1][1] = i
        else:
            runs.append([i, i, b["leader"]])

    out = []
    for k, (a, z, team) in enumerate(runs):
        if k == 0 or team is None or z - a + 1 < MIN_RUN_BLOCKS:
            continue
        pa, pz, _ = runs[k - 1]
        run, prev = timeline[a:z + 1], timeline[pa:pz + 1]
        mine = sum(b["threat"][team] for b in run)
        theirs = sum(b["threat"][other(team)] for b in run)
        if mine - theirs < MIN_SHIFT_MARGIN:
            continue

        contributors = {}
        for b in run:
            for e in b["events"]:
                if e["team"] == team and threat(e) > 0:
                    contributors[e["player"]] = contributors.get(e["player"], 0) + threat(e)
        top = sorted(contributors, key=contributors.get, reverse=True)[:3]

        first = run[0]["events"][0]
        anchor = {**first, "minute": run[0]["start"], "second": 0}
        last = run[-1]["events"][-1]
        out.append(moment("momentum_shift", anchor, team, top, {
            "start_minute": run[0]["start"], "last_minute": last["minute"],
            "end_period": last["period"],
            "blocks": len(run), "block_minutes": BLOCK_MINUTES,
            "team_threat": round(mine, 4), "opponent_threat": round(theirs, 4),
            "opponent_blocks_ahead_before": len(prev),
            "team_threat_before": round(sum(b["threat"][team] for b in prev), 4),
            "opponent_threat_before": round(sum(b["threat"][other(team)] for b in prev), 4),
            "top_player_threat": round(contributors[top[0]], 4),
        }, score[first["event_id"] - 1] if first["event_id"] > 1 else dict.fromkeys(TEAMS, 0),
            mine - theirs))
    return out


def select(cands):
    chosen = [c for c in cands if c["category"] == "goal"]
    counts = {"goal": len(chosen)}
    for category in PRIORITY:
        for c in sorted((c for c in cands if c["category"] == category),
                        key=lambda c: c["_score"], reverse=True):
            if counts.get(category, 0) >= MAX_PER_CATEGORY:
                break
            if any(c["period"] == m["period"] and abs(clock(c) - clock(m)) < MIN_GAP_SECONDS
                   for m in chosen):
                continue
            chosen.append(c)
            counts[category] = counts.get(category, 0) + 1

    chosen.sort(key=lambda c: (c["period"], clock(c)))
    out = []
    for i, c in enumerate(chosen, start=1):
        c = {k: v for k, v in c.items() if k != "_score"}
        out.append({"id": f"m{i:02d}", **c})
    return out


def build(path=DATA_DIR / "match_xt.csv"):
    events = load(path)
    final = scores_after(events)[events[-1]["event_id"]]
    return {"final_score": final, "moments": select(candidates(events))}


def main():
    result = build()
    (DATA_DIR / "key_moments.json").write_text(json.dumps(result, indent=2) + "\n",
                                               encoding="utf-8")
    print(f"Wrote {len(result['moments'])} moments to data/key_moments.json\n")
    for m in result["moments"]:
        print(f"  {m['id']}  P{m['period']} {m['minute']:>2}:{m['second']:02d}  "
              f"{m['team'].replace('london_', ''):<4}  {m['category']:<20} "
              f"{', '.join(m['players'])}")
        print("        " + ", ".join(f"{k}={v}" for k, v in m["facts"].items()))


if __name__ == "__main__":
    main()
