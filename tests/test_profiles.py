"""Checks profile validation and moment selection (src/profiles.py). No model calls."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from profiles import (FAN_MAX_MOMENTS, Profile, ProfileError, involves_favourite, select,  # noqa: E402
                      selection_problems)

MOMENTS = json.loads((ROOT / "data" / "key_moments.json").read_text())["moments"]
ANALYSIS = json.loads((ROOT / "data" / "analysis.json").read_text(encoding="utf-8"))["analysis"]
PLAYERS = json.loads((ROOT / "data" / "player_summaries.json").read_text())["players"]
ALL = [m["id"] for m in MOMENTS]


def profile(text):
    return Profile.parse(text, players=PLAYERS)


def chosen(text):
    return select(profile(text), MOMENTS, ANALYSIS, PLAYERS)


@pytest.mark.parametrize("data, error", [
    ({"mode": "pundit", "voice": "studio", "language": "en"}, "mode"),
    ({"mode": "fan", "voice": "radio", "language": "en"}, "voice"),
    ({"mode": "fan", "voice": "studio", "language": "fr"}, "language"),
    ({"mode": "fan", "voice": "studio", "language": "en", "favourite_team": "London Red"}, "favourite_team"),
    ({"mode": "fan", "voice": "studio", "language": "en", "focus_player": "Cass Dunmor"}, "focus_player"),
    ({"mode": "fan", "voice": "studio", "language": "en", "focus_player": "Owen Strand"}, "focus_player"),
    ({"mode": "fan", "voice": "studio"}, "missing"),
    ({"mode": "fan", "voice": "studio", "language": "en", "colour": "red"}, "unknown"),
])
def test_invalid_profiles_are_rejected(data, error):
    with pytest.raises(ProfileError, match=error):
        Profile.from_dict(data, players=PLAYERS)


def test_profile_key():
    assert profile("analyst/studio/en/none").key() == "analyst-studio-en-none-none"
    assert profile("fan/stadium/en/none/Cass Dunmore").key() == "fan-stadium-en-none-cass_dunmore"
    assert profile("fan/studio/ar/london_red").key() == "fan-studio-ar-london_red-none"


def test_analyst_gets_every_moment_in_story_order():
    assert chosen("analyst/studio/en/none") == ALL


def test_fan_with_no_favourite_gets_the_goals_and_turning_point():
    assert ANALYSIS["turning_point"]["moment_id"] == "m10"  # a goal, so no extra moment
    assert chosen("fan/studio/en/none") == ["m07", "m10", "m11"]


def test_fan_red_takes_the_top_3_supporting_moments_by_xt_added():
    # London Red is involved in every supporting moment; only m03, m05 and m06
    # have an xt_added (0.0758, 0.0755, 0.0725), so they rank first.
    assert chosen("fan/studio/en/london_red") == ["m03", "m05", "m06", "m07", "m10", "m11"]


def test_fan_ranking_puts_moments_without_xt_added_last():
    by_id = {m["id"]: m for m in MOMENTS}
    # Only m03 keeps its xt_added: it ranks first, then the rest in match order (m01, m02).
    trimmed = [m if m["id"] == "m03" else {**m, "facts": {k: v for k, v in m["facts"].items() if k != "xt_added"}}
               for m in MOMENTS]
    ids = select(profile("fan/studio/en/london_red"), trimmed, ANALYSIS, PLAYERS)
    assert ids == ["m01", "m02", "m03", "m07", "m10", "m11"]
    assert by_id["m03"]["facts"]["xt_added"] == 0.0758


def test_fan_blue_has_fewer_than_3_supporting_candidates():
    # Only m01 (Bram Hollis) and m08 (Niko Vane, Kai Renwick) name London Blue players.
    assert chosen("fan/stadium/en/london_blue") == ["m01", "m07", "m08", "m10", "m11"]


@pytest.mark.parametrize("text", ["fan/studio/en/london_red", "fan/stadium/en/london_blue",
                                  "fan/stadium/en/none/Cass Dunmore", "fan/studio/en/none/Theo Brannick"])
def test_fan_is_capped_and_in_match_order(text):
    ids = chosen(text)
    assert len(ids) <= FAN_MAX_MOMENTS
    assert ids == [i for i in ALL if i in ids]


def test_no_favourite_team_reordering_only_a_flag():
    ids = chosen("analyst/studio/en/london_blue")
    assert ids == ALL
    by_id = {m["id"]: m for m in MOMENTS}
    flagged = [i for i in ids if involves_favourite(profile("analyst/studio/en/london_blue"), by_id[i], PLAYERS)]
    assert flagged == ["m01", "m07", "m08"]
    assert not any(involves_favourite(profile("analyst/studio/en/none"), m, PLAYERS) for m in MOMENTS)


def test_focus_player_gets_every_moment_involving_them_in_either_mode():
    dunmore = ["m01", "m03", "m04", "m05", "m06", "m09", "m11"]
    assert chosen("fan/stadium/en/none/Cass Dunmore") == dunmore
    assert chosen("analyst/studio/en/none/Cass Dunmore") == dunmore
    assert chosen("fan/studio/en/london_blue/Cass Dunmore") == dunmore  # focus wins over the favourite team


def test_focus_view_is_not_capped():
    # Every moment rewritten to name Cass Dunmore: a focus view takes all 11, no cap of 7.
    named = [{**m, "players": m["players"] + ["Cass Dunmore"]} for m in MOMENTS]
    p = profile("fan/stadium/en/none/Cass Dunmore")
    ids = select(p, named, ANALYSIS, PLAYERS)
    assert ids == ALL and len(ids) > FAN_MAX_MOMENTS
    assert selection_problems(p, ids, named, ANALYSIS, PLAYERS) == []


def test_selection_with_a_moment_not_involving_the_focus_player_fails():
    p = profile("fan/stadium/en/none/Cass Dunmore")
    good = select(p, MOMENTS, ANALYSIS, PLAYERS)
    assert selection_problems(p, good, MOMENTS, ANALYSIS, PLAYERS) == []
    problems = selection_problems(p, good + ["m07"], MOMENTS, ANALYSIS, PLAYERS)
    assert problems == ["m07 does not involve the focus player Cass Dunmore"]


def test_fan_selection_over_the_cap_fails():
    p = profile("fan/studio/en/london_red")
    problems = selection_problems(p, ALL[:8], MOMENTS, ANALYSIS, PLAYERS)
    assert f"fan mode has 8 moments, at most {FAN_MAX_MOMENTS}" in problems
