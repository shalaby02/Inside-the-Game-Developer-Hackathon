"""Match summary: whole-match facts for the Analyst, computed in code.

Reads data/match_xt.csv and data/key_moments.json (never changes either)
and writes data/match_summary.json. Facts only: the final score and
result_line (the result in words, built from the goal timeline), the goal
timeline, each lead and how long it lasted (a lead to full time has no
length: the whistle isn't recorded), first_half_summary, per-team stats for
each half, the goals inside each momentum shift, and the key-moment ids in
match order.

Definitions (see docs/data-format.md, "Analysis terms"). Every event is in
the acting team's frame, attacking toward x = 100:
- thirds: defensive x < 33.3, middle 33.3 <= x < 66.7, final x >= 66.7.
- threat_created: xt_added of completed passes and carries (the same
  threat as src/key_moments.py).
- final_third_entries: completed passes and carries that start outside the
  final third and end in it.
- penalty_area_entries: completed passes and carries that start outside the
  penalty area (x >= 83, 21 <= y <= 79) and end in it.
- progressive_actions: completed passes and carries that move the ball at
  least PROGRESSIVE_M metres closer to the middle of the goal: 30 within the
  team's own half, 15 from its own half into the other half, 10 within the
  other half. These thresholds are this project's own definition.
- possessions_lost_in_final_third: incomplete passes and lost carries that
  start in the final third (the team gave the ball away there).
- shots: every shot. saves: shots by the other team that this team's
  goalkeeper saved.

Run:  python src/match_summary.py
"""

import json
import math
from pathlib import Path

from key_moments import PITCH_M, TEAM_NAMES, TEAMS, clock, load, other, scores_after, threat

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

FINAL_THIRD_X = 200 / 3   # 66.7, the same edges as zone() in src/key_moments.py
MIDDLE_THIRD_X = 100 / 3  # 33.3
PENALTY_AREA = {"min_x": 83, "min_y": 21, "max_y": 79}  # docs/data-format.md
HALFWAY_X = 50
# (start in own half, end in own half) -> metres closer to goal needed
PROGRESSIVE_M = {(True, True): 30, (True, False): 15, (False, False): 10}
HALVES = {1: "first_half", 2: "second_half"}
SECOND_HALF_START = 45 * 60  # the second-half clock starts at 45:00


def completed_move(e):
    return e["type"] in ("pass", "carry") and e["outcome"] == "complete"


def third(x):
    return "final" if x >= FINAL_THIRD_X else "middle" if x >= MIDDLE_THIRD_X else "defensive"


def in_penalty_area(x, y):
    return x >= PENALTY_AREA["min_x"] and PENALTY_AREA["min_y"] <= y <= PENALTY_AREA["max_y"]


def goal_distance_m(x, y):
    return math.hypot((100 - x) * PITCH_M[0] / 100, (50 - y) * PITCH_M[1] / 100)


def final_third_entry(e):
    return completed_move(e) and third(e["start_x"]) != "final" and third(e["end_x"]) == "final"


def penalty_area_entry(e):
    return (completed_move(e) and not in_penalty_area(e["start_x"], e["start_y"])
            and in_penalty_area(e["end_x"], e["end_y"]))


def progressive(e):
    if not completed_move(e):
        return False
    need = PROGRESSIVE_M.get((e["start_x"] < HALFWAY_X, e["end_x"] < HALFWAY_X))
    gained = goal_distance_m(e["start_x"], e["start_y"]) - goal_distance_m(e["end_x"], e["end_y"])
    return need is not None and gained >= need


def possession_lost_in_final_third(e):
    lost = (e["type"] == "pass" and e["outcome"] == "incomplete") or (e["type"] == "carry" and e["outcome"] == "lost")
    return lost and third(e["start_x"]) == "final"


def half_stats(events, team):
    own = [e for e in events if e["team"] == team]
    return {
        "threat_created": round(sum(threat(e) for e in own), 4),
        "final_third_entries": sum(map(final_third_entry, own)),
        "penalty_area_entries": sum(map(penalty_area_entry, own)),
        "progressive_actions": sum(map(progressive, own)),
        "possessions_lost_in_final_third": sum(map(possession_lost_in_final_third, own)),
        "shots": sum(e["type"] == "shot" for e in own),
        "saves": sum(e["type"] == "shot" and e["outcome"] == "saved" for e in events if e["team"] == other(team)),
    }


def match_seconds(events):
    """A function giving each (period, minute, second) its seconds since kick-off,
    so a lead across half-time counts both halves' stoppage time correctly."""
    first_half_end = max(clock(e) for e in events if e["period"] == 1)

    def at(period, minute, second):
        t = minute * 60 + second
        return t if period == 1 else first_half_end + t - SECOND_HALF_START
    return at


def goals_and_leads(events, moments):
    after = scores_after(events)
    moment_at = {(m["period"], m["minute"], m["second"]): m["id"] for m in moments if m["category"] == "goal"}
    goals = [{"moment_id": moment_at.get((e["period"], e["minute"], e["second"])),
              "period": e["period"], "minute": e["minute"], "second": e["second"],
              "team": e["team"], "scorer": e["player"], "score_after": after[e["event_id"]]}
             for e in events if e["type"] == "shot" and e["outcome"] == "goal"]

    at = match_seconds(events)
    # Each goal starts a new state of the score; it lasts until the next goal or full time.
    # Full time isn't recorded (the last event is not the whistle), so a lead that lasts
    # to the end has no end time and no length.
    ends = [(g["period"], g["minute"], g["second"]) for g in goals[1:]] + [None]
    leads = []
    for g, end in zip(goals, ends):
        score = g["score_after"]
        if score[TEAMS[0]] == score[TEAMS[1]]:
            continue
        lead = {"team": max(TEAMS, key=score.get), "from_period": g["period"], "from_minute": g["minute"],
                "from_second": g["second"]}
        if end:
            lead.update(to_period=end[0], to_minute=end[1], to_second=end[2], ends_at="goal",
                        seconds=at(*end) - at(g["period"], g["minute"], g["second"]))
        else:
            lead["ends_at"] = "full_time"
        leads.append(lead)
    # Back-to-back leads for one team (2-0 after 1-0) are one lead.
    merged = []
    for lead in leads:
        prev = merged[-1] if merged else None
        if prev and prev["team"] == lead["team"] and prev["ends_at"] == "goal" and (
                prev["to_period"], prev["to_minute"], prev["to_second"]) == (
                lead["from_period"], lead["from_minute"], lead["from_second"]):
            head = {k: prev[k] for k in ("team", "from_period", "from_minute", "from_second")}
            merged[-1] = {**head, **{k: v for k, v in lead.items() if k not in head}}
            if lead["ends_at"] == "goal":
                merged[-1]["seconds"] = prev["seconds"] + lead["seconds"]
        else:
            merged.append(lead)
    return goals, merged


def minutes_led(leads):
    """Minutes each team led, from leads that ended at a goal. None for a team
    whose lead lasted to full time, which has no recorded end."""
    out = {}
    for t in TEAMS:
        own = [lead for lead in leads if lead["team"] == t]
        out[t] = None if any(lead["ends_at"] == "full_time" for lead in own) else round(
            sum(lead["seconds"] for lead in own) / 60, 1)
    return out


def ordinal(n):
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def result_line(final, leads):
    """The result in words, from the goal timeline, e.g. "London Red won 2-1
    after trailing from the 61st minute to the 74th"."""
    a, b = TEAMS
    if final[a] == final[b]:
        return f"{TEAM_NAMES[a]} and {TEAM_NAMES[b]} drew {final[a]}-{final[b]}"
    winner = max(TEAMS, key=final.get)
    line = f"{TEAM_NAMES[winner]} won {final[winner]}-{final[other(winner)]}"
    trailing = [lead for lead in leads if lead["team"] == other(winner)]  # these always end at a goal
    if trailing:
        line += " after trailing " + " and ".join(
            f"from the {ordinal(lead['from_minute'])} minute to the {ordinal(lead['to_minute'])}" for lead in trailing)
    return line


def goals_in_run(moment, goals):
    """Ids of the goals inside a momentum shift: from the start of its first block
    to the end of its last minute (last_minute, in end_period)."""
    f = moment["facts"]
    start = (moment["period"], f["start_minute"] * 60)
    end = (f["end_period"], f["last_minute"] * 60 + 59)
    return [g["moment_id"] for g in goals
            if start <= (g["period"], g["minute"] * 60 + g["second"]) <= end]


def build(xt_path=DATA_DIR / "match_xt.csv", moments_path=DATA_DIR / "key_moments.json"):
    events = load(xt_path)
    moments = json.loads(Path(moments_path).read_text(encoding="utf-8"))["moments"]
    goals, leads = goals_and_leads(events, moments)
    final = scores_after(events)[events[-1]["event_id"]]
    by_half = {name: {t: half_stats([e for e in events if e["period"] == p], t) for t in TEAMS}
               for p, name in HALVES.items()}
    return {
        "teams": TEAM_NAMES,
        "final_score": final,
        "result_line": result_line(final, leads),
        "goals": goals,
        "leads": leads,
        "minutes_led": minutes_led(leads),
        "first_half_summary": {t: {"threat_created": by_half["first_half"][t]["threat_created"],
                                   "shots": by_half["first_half"][t]["shots"],
                                   "goals": sum(g["team"] == t and g["period"] == 1 for g in goals)}
                               for t in TEAMS},
        "by_half": by_half,
        "momentum_runs": [{"moment_id": m["id"], "team": m["team"], "goals_in_run": goals_in_run(m, goals)}
                          for m in moments if m["category"] == "momentum_shift"],
        "moment_ids": [m["id"] for m in moments],
    }


def main():
    summary = build()
    (DATA_DIR / "match_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("Wrote data/match_summary.json")
    for g in summary["goals"]:
        s = g["score_after"]
        print(f"  {g['minute']}:{g['second']:02d}  {TEAM_NAMES[g['team']]:<11}  {g['scorer']:<14}  "
              f"{s['london_red']}-{s['london_blue']}  ({g['moment_id']})")
    for lead in summary["leads"]:
        to = (f"{lead['to_minute']}:{lead['to_second']:02d} ({lead['seconds']} s)" if lead["ends_at"] == "goal"
              else "full time (no recorded end)")
        print(f"  {TEAM_NAMES[lead['team']]} led from {lead['from_minute']}:{lead['from_second']:02d} to {to}")
    print(f"  {summary['result_line']}")


if __name__ == "__main__":
    main()
