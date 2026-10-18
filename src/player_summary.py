"""Player summaries: per-player facts for the Personalizer, computed in code.

Reads data/match_xt.csv and data/key_moments.json (never changes either) and
writes data/player_summaries.json. Facts only, no prose, for every player who
appears in at least one key moment or took at least one shot:

- team: the team id (london_red / london_blue).
- passes_completed, passes_attempted: every pass event, and the complete ones.
- xt_added: xt_added of the player's completed passes and carries, to 4
  decimals (the same "threat created" as src/match_summary.py).
- final_third_entries: completed passes and carries that start outside the
  final third and end in it (match_summary.final_third_entry).
- shots: every shot the player took.
- saves (goalkeepers only): shots by the other team that were saved. Saves
  have no event of their own, so a saved shot is credited to the other
  team's goalkeeper (docs/data-format.md).
- moment_ids: the key moments whose players list names the player, in match order.

Players are listed by team (London Red first), then shirt number.

Run:  python src/player_summary.py
"""

import json
from pathlib import Path

from key_moments import GOALKEEPERS, TEAMS, load, other, threat
from match_summary import final_third_entry

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_PATH = DATA_DIR / "player_summaries.json"


def player_facts(events, moments, name, team):
    own = [e for e in events if e["player"] == name and e["team"] == team]
    passes = [e for e in own if e["type"] == "pass"]
    facts = {
        "team": team,
        "passes_completed": sum(e["outcome"] == "complete" for e in passes),
        "passes_attempted": len(passes),
        "xt_added": round(sum(threat(e) for e in own), 4),
        "final_third_entries": sum(map(final_third_entry, own)),
        "shots": sum(e["type"] == "shot" for e in own),
    }
    if GOALKEEPERS[team] == name:
        facts["saves"] = sum(e["type"] == "shot" and e["outcome"] == "saved"
                             for e in events if e["team"] == other(team))
    facts["moment_ids"] = [m["id"] for m in moments if name in m["players"]]
    return facts


def build(xt_path=DATA_DIR / "match_xt.csv", moments_path=DATA_DIR / "key_moments.json"):
    events = load(xt_path)
    moments = json.loads(Path(moments_path).read_text(encoding="utf-8"))["moments"]
    # (team, shirt number) identifies a player; the name is for display (docs/data-format.md).
    roster = {(e["team"], e["shirt_number"]): e["player"] for e in events}
    in_moments = {p for m in moments for p in m["players"]}
    shooters = {e["player"] for e in events if e["type"] == "shot"}
    keys = sorted((k for k, name in roster.items() if name in in_moments | shooters),
                  key=lambda k: (TEAMS.index(k[0]), k[1]))
    return {"players": {roster[k]: player_facts(events, moments, roster[k], k[0]) for k in keys}}


def main():
    summaries = build()
    OUT_PATH.write_text(json.dumps(summaries, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_PATH.relative_to(ROOT)}: {len(summaries['players'])} players")
    for name, f in summaries["players"].items():
        saves = f" saves {f['saves']}" if "saves" in f else ""
        print(f"  {name:<15} {f['team']:<11} passes {f['passes_completed']}/{f['passes_attempted']}  "
              f"xT {f['xt_added']:+.4f}  F3 {f['final_third_entries']}  shots {f['shots']}{saves}  "
              f"{','.join(f['moment_ids']) or '-'}")


if __name__ == "__main__":
    main()
