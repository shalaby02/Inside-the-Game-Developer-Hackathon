"""Checks that src/key_moments.py finds the planted story moments
(docs/match-story.md) and follows its selection rules."""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import key_moments as km  # noqa: E402

REQUIRED_FACTS = {
    "goal": {"shot_zone_value", "possession_seconds", "team_score", "opponent_score"},
    "save": {"shot_zone_value", "distance_to_goal_m", "team_score", "opponent_score"},
    "big_chance_missed": {"shot_zone_value", "distance_to_goal_m", "team_score", "opponent_score"},
    "momentum_shift": {"start_minute", "last_minute", "team_threat", "opponent_threat",
                       "team_score", "opponent_score"},
    "biggest_threat_swing": {"xt_added", "zone_start_value", "zone_end_value",
                             "team_score", "opponent_score"},
}


@pytest.fixture(scope="module")
def moments():
    return km.build()["moments"]


def at(moments, minute, team):
    found = [m for m in moments if m["minute"] == minute and m["team"] == team]
    assert found, f"no {team} moment at {minute}'"
    return found[0]


def test_38_big_miss(moments):
    m = at(moments, 38, "london_red")
    assert m["category"] == "big_chance_missed"
    assert m["players"][0] == "Cass Dunmore"


def test_61_blue_goal(moments):
    m = at(moments, 61, "london_blue")
    assert m["category"] == "goal"
    assert m["players"] == ["Niko Vane", "Dario Quill"]
    assert (m["facts"]["team_score"], m["facts"]["opponent_score"]) == (1, 0)


def test_67_harwick_save(moments):
    m = at(moments, 67, "london_red")
    assert m["category"] == "save"
    assert m["players"][0] == "Ellis Harwick"


def test_74_counter_goal(moments):
    m = at(moments, 74, "london_red")
    assert m["category"] == "goal"
    assert m["facts"]["possession_seconds"] == 12
    assert "counter" in m["tags"]


def test_89_late_winner(moments):
    m = at(moments, 89, "london_red")
    assert m["category"] == "goal"
    assert m["players"] == ["Cass Dunmore", "Theo Brannick"]
    assert (m["facts"]["team_score"], m["facts"]["opponent_score"]) == (2, 1)


def test_70_momentum_shift_to_red(moments):
    m = at(moments, 70, "london_red")
    assert m["category"] == "momentum_shift"
    assert m["period"] == 2
    assert m["facts"]["last_minute"] >= 90


def test_facts_complete_and_numeric(moments):
    for m in moments:
        assert isinstance(m["tags"], list)
        missing = REQUIRED_FACTS[m["category"]] - m["facts"].keys()
        assert not missing, f"{m['id']} is missing {missing}"
        for k, v in m["facts"].items():
            assert isinstance(v, (int, float)) and not isinstance(v, bool), f"{m['id']}.{k}={v!r}"
            assert math.isfinite(v), f"{m['id']}.{k} is {v}"


def test_selection_rules(moments):
    goals = [e for e in km.load(km.DATA_DIR / "match_xt.csv")
             if e["type"] == "shot" and e["outcome"] == "goal"]
    assert sum(m["category"] == "goal" for m in moments) == len(goals)

    for category in REQUIRED_FACTS:
        assert sum(m["category"] == category for m in moments) <= km.MAX_PER_CATEGORY

    for a in moments:
        for b in moments:
            if a is not b and a["period"] == b["period"]:
                assert abs(km.clock(a) - km.clock(b)) >= km.MIN_GAP_SECONDS, (a["id"], b["id"])
