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
WORD_FACTS = {"action_type", "score_effect", "build_up", "counter_label"}  # the only non-numeric facts


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
            if k in WORD_FACTS:
                assert isinstance(v, str) and v, f"{m['id']}.{k}={v!r}"
                continue
            assert isinstance(v, (int, float)) and not isinstance(v, bool), f"{m['id']}.{k}={v!r}"
            assert math.isfinite(v), f"{m['id']}.{k} is {v}"


def test_action_type_on_every_key_action(moments):
    events = km.load(km.DATA_DIR / "match_xt.csv")
    for m in moments:
        has_key_action = m["category"] == "biggest_threat_swing" or "key_pass_xt_added" in m["facts"]
        assert ("action_type" in m["facts"]) == has_key_action, m["id"]
        if not has_key_action:
            continue
        assert m["facts"]["action_type"] in ("pass", "carry"), m["id"]
        if m["category"] == "biggest_threat_swing":
            # the swing's own event: same team, time and player
            e = next(e for e in events if (e["period"], e["minute"], e["second"], e["team"], e["player"])
                     == (m["period"], m["minute"], m["second"], m["team"], m["players"][0]))
            assert m["facts"]["action_type"] == e["type"], m["id"]
        else:
            assert m["facts"]["action_type"] == "pass", m["id"]  # a key pass is always a pass


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


def test_score_effect_on_goals_only(moments):
    effects = {m["minute"]: m["facts"].get("score_effect") for m in moments if m["category"] == "goal"}
    assert effects == {61: "put London Blue 1-0 up", 74: "levelled the match at 1-1", 89: "put London Red 2-1 ahead"}
    assert all("score_effect" not in m["facts"] for m in moments if m["category"] != "goal")


@pytest.mark.parametrize("after,expected", [
    ({"london_red": 1, "london_blue": 0}, "put London Red 1-0 up"),
    ({"london_red": 2, "london_blue": 1}, "put London Red 2-1 ahead"),
    ({"london_red": 1, "london_blue": 1}, "levelled the match at 1-1"),
    ({"london_red": 2, "london_blue": 0}, "extended London Red's lead to 2-0"),
    ({"london_red": 1, "london_blue": 2}, "pulled London Red back to 1-2"),
])
def test_score_effect_wording(after, expected):
    assert km.score_effect("london_red", after) == expected


def test_counter_labels(moments):
    labels = {m["minute"]: m["facts"].get("counter_label") for m in moments if "counter" in m["tags"]}
    assert labels == {61: "the fastest of the match's two counter-attacks",
                      74: "the second-fastest of the match's two counter-attacks"}
    assert all("counter_label" not in m["facts"] for m in moments if "counter" not in m["tags"])


def test_build_up_from_possession_events(moments):
    by_minute = {m["minute"]: m["facts"].get("build_up") for m in moments}
    assert by_minute[61] == ("won the ball back in midfield and scored 10 seconds later, "
                             "after 2 passes and a carry from midfield into the attacking third")
    assert by_minute[74] == ("won the ball back in the defensive third and scored 12 seconds later, "
                             "after 3 passes and a carry from midfield into the attacking third")
    assert by_minute[38] == "built through 3 passes"
    assert by_minute[55] == "started after a London Blue foul"


def test_build_up_duration_only_after_a_won_ball(moments):
    for m in moments:
        text = m["facts"].get("build_up", "")
        assert ("second" in text) == text.startswith("won the ball back"), m["id"]
        if text.startswith("won the ball back") and "possession_seconds" in m["facts"]:
            # a shot moment's duration runs from the won ball to the shot, so it is the possession time
            assert f" {m['facts']['possession_seconds']} second" in text, m["id"]
    assert all("build_up" not in m["facts"] for m in moments if m["category"] == "momentum_shift")


def ev(event_id, player, type_, outcome="complete", second=0, team="london_red", x=50.0, end_x=None):
    return {"event_id": event_id, "player": player, "type": type_, "outcome": outcome, "team": team,
            "minute": 10, "second": second, "start_x": x, "end_x": x if end_x is None else end_x}


def test_build_up_one_two_and_unknown_start():
    events = [ev(1, "A", "pass"), ev(2, "B", "pass"), ev(3, "A", "carry", x=50, end_x=75),
              ev(4, "A", "shot", "goal")]
    # no won ball and no opponent foul before it: no start, no duration
    assert km.build_up(None, events, events[-1], "scored") == (
        "built through 2 passes, a carry from midfield into the attacking third and a one-two")


def test_build_up_ignores_short_carries_and_counts_seconds():
    events = [ev(1, "A", "interception", "won", second=5, x=20), ev(2, "A", "carry", second=6, x=20, end_x=25),
              ev(3, "A", "shot", "off_target", second=6)]
    assert km.build_up(None, events, events[-1], "shot") == (
        "won the ball back in the defensive third and shot 1 second later")


def test_no_build_up_without_a_known_start_or_move():
    events = [ev(1, "A", "pass", x=70)]
    prev_own_foul = ev(0, "B", "foul", "free_kick", team="london_red")
    assert km.build_up(prev_own_foul, events, events[0], "passed") is None
