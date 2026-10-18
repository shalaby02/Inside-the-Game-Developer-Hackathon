"""Checks src/player_summary.py against the frozen match data. No model calls."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import player_summary as ps  # noqa: E402
from key_moments import load  # noqa: E402
from match_summary import build as build_summary  # noqa: E402

PLAYERS = ps.build()["players"]
EVENTS = load(ROOT / "data" / "match_xt.csv")
MOMENTS = json.loads((ROOT / "data" / "key_moments.json").read_text())["moments"]
SUMMARY = build_summary()


def test_saved_file_is_up_to_date():
    assert json.loads((ROOT / "data" / "player_summaries.json").read_text()) == json.loads(json.dumps(ps.build()))


def test_every_player_in_a_moment_or_with_a_shot_and_no_one_else():
    expected = {p for m in MOMENTS for p in m["players"]} | {e["player"] for e in EVENTS if e["type"] == "shot"}
    assert set(PLAYERS) == expected


def test_cass_dunmore():
    f = PLAYERS["Cass Dunmore"]
    assert f["team"] == "london_red"
    assert f["moment_ids"] == ["m01", "m03", "m04", "m05", "m06", "m09", "m11"]
    assert (f["passes_completed"], f["passes_attempted"], f["shots"]) == (28, 34, 7)
    assert "saves" not in f


def test_only_goalkeepers_have_saves_and_they_match_the_summary():
    keepers = {n: f for n, f in PLAYERS.items() if "saves" in f}
    assert set(keepers) == {"Ellis Harwick", "Bram Hollis"}
    for name, f in keepers.items():
        halves = SUMMARY["by_half"]
        assert f["saves"] == sum(halves[h][f["team"]]["saves"] for h in halves)


def test_shots_add_up_to_the_match_total():
    for team in ("london_red", "london_blue"):
        total = sum(SUMMARY["by_half"][h][team]["shots"] for h in SUMMARY["by_half"])
        assert sum(f["shots"] for f in PLAYERS.values() if f["team"] == team) == total


def test_passes_and_xt_match_the_events():
    for name, f in PLAYERS.items():
        own = [e for e in EVENTS if e["player"] == name]
        passes = [e for e in own if e["type"] == "pass"]
        assert f["passes_attempted"] == len(passes) >= f["passes_completed"]
        moves = [e["xt_added"] for e in own if e["type"] in ("pass", "carry") and e["outcome"] == "complete"]
        assert f["xt_added"] == round(sum(moves), 4)


def test_final_third_entries_only_from_completed_moves():
    # Rafael Tovey's figure, recounted by hand from the definition.
    own = [e for e in EVENTS if e["player"] == "Rafael Tovey" and e["type"] in ("pass", "carry")
           and e["outcome"] == "complete" and e["start_x"] < 200 / 3 <= e["end_x"]]
    assert PLAYERS["Rafael Tovey"]["final_third_entries"] == len(own)
