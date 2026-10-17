"""Checks src/match_summary.py against the frozen match data. No model calls."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import match_summary as ms  # noqa: E402

SUMMARY = ms.build()


def ev(type_, sx, sy, ex, ey, outcome="complete"):
    return {"type": type_, "start_x": sx, "start_y": sy, "end_x": ex, "end_y": ey, "outcome": outcome}


def test_final_score_and_goal_timeline():
    assert SUMMARY["final_score"] == {"london_red": 2, "london_blue": 1}
    timeline = [(g["moment_id"], g["minute"], g["second"], g["team"], g["scorer"],
                 g["score_after"]["london_red"], g["score_after"]["london_blue"]) for g in SUMMARY["goals"]]
    assert timeline == [
        ("m07", 61, 14, "london_blue", "Niko Vane", 0, 1),
        ("m10", 74, 22, "london_red", "Rafael Tovey", 1, 1),
        ("m11", 89, 30, "london_red", "Cass Dunmore", 2, 1),
    ]


def test_blue_lead_runs_from_61_14_to_74_22():
    blue = [lead for lead in SUMMARY["leads"] if lead["team"] == "london_blue"]
    assert len(blue) == 1
    lead = blue[0]
    assert (lead["from_period"], lead["from_minute"], lead["from_second"]) == (2, 61, 14)
    assert (lead["to_period"], lead["to_minute"], lead["to_second"]) == (2, 74, 22)
    assert lead["ends_at"] == "goal" and lead["seconds"] == 13 * 60 + 8


def test_red_lead_runs_to_full_time_with_no_length():
    [red] = [lead for lead in SUMMARY["leads"] if lead["team"] == "london_red"]
    assert (red["from_minute"], red["from_second"]) == (89, 30)
    # Full time isn't recorded, so the lead has no end time and no length.
    assert red["ends_at"] == "full_time"
    assert not {"to_minute", "to_second", "seconds"} & set(red)
    assert SUMMARY["minutes_led"] == {"london_red": None, "london_blue": 13.1}
    assert "237" not in json.dumps(SUMMARY)


def test_result_line():
    assert SUMMARY["result_line"] == "London Red won 2-1 after trailing from the 61st minute to the 74th"
    assert ms.result_line({"london_red": 1, "london_blue": 1}, []) == "London Red and London Blue drew 1-1"
    assert ms.result_line({"london_red": 1, "london_blue": 0}, [{"team": "london_red"}]) == "London Red won 1-0"
    assert ms.ordinal(1) == "1st" and ms.ordinal(12) == "12th" and ms.ordinal(22) == "22nd" and ms.ordinal(93) == "93rd"


def test_first_half_summary():
    assert SUMMARY["first_half_summary"] == {
        "london_red": {"threat_created": 1.4019, "shots": 9, "goals": 0},
        "london_blue": {"threat_created": 0.1746, "shots": 2, "goals": 0},
    }
    for team in ("london_red", "london_blue"):
        half = SUMMARY["by_half"]["first_half"][team]
        assert SUMMARY["first_half_summary"][team]["threat_created"] == half["threat_created"]
        assert SUMMARY["first_half_summary"][team]["shots"] == half["shots"]


def test_goals_in_run():
    runs = {r["moment_id"]: r for r in SUMMARY["momentum_runs"]}
    assert set(runs) == {"m02", "m09"}  # every momentum moment
    assert runs["m02"]["goals_in_run"] == []            # 20th to 46th minute of the first half
    assert runs["m09"]["goals_in_run"] == ["m10", "m11"]  # 70th to 93rd minute: not m07 at 61:14
    shift = {"period": 2, "facts": {"start_minute": 60, "last_minute": 61, "end_period": 2}}
    goal = {"moment_id": "g", "period": 2, "minute": 61, "second": 14}
    assert ms.goals_in_run(shift, [goal]) == ["g"]
    assert ms.goals_in_run({**shift, "period": 1, "facts": {**shift["facts"], "end_period": 1}}, [goal]) == []


def test_lead_across_half_time_counts_both_halves():
    events = [
        {"event_id": 1, "period": 1, "minute": 40, "second": 0, "team": "london_red", "player": "A",
         "type": "shot", "outcome": "goal"},
        {"event_id": 2, "period": 1, "minute": 46, "second": 0, "team": "london_blue", "player": "B",
         "type": "pass", "outcome": "complete"},
        {"event_id": 3, "period": 2, "minute": 50, "second": 0, "team": "london_blue", "player": "B",
         "type": "shot", "outcome": "goal"},
    ]
    _, [lead] = ms.goals_and_leads(events, [])
    # 40:00 to 46:00 in the first half (stoppage included), then 45:00 to 50:00
    assert lead["seconds"] == 6 * 60 + 5 * 60 and ms.minutes_led([lead])["london_red"] == 11.0


def test_halves_have_every_stat_for_both_teams():
    stats = {"threat_created", "final_third_entries", "penalty_area_entries", "progressive_actions",
             "possessions_lost_in_final_third", "shots", "saves"}
    for half in ("first_half", "second_half"):
        for team in ("london_red", "london_blue"):
            assert set(SUMMARY["by_half"][half][team]) == stats


def test_shots_and_saves_add_up():
    events = ms.load(ms.DATA_DIR / "match_xt.csv")
    for team in ("london_red", "london_blue"):
        shots = sum(e["type"] == "shot" and e["team"] == team for e in events)
        assert sum(SUMMARY["by_half"][h][team]["shots"] for h in ("first_half", "second_half")) == shots
        saved_against = sum(e["type"] == "shot" and e["outcome"] == "saved" and e["team"] != team for e in events)
        assert sum(SUMMARY["by_half"][h][team]["saves"] for h in ("first_half", "second_half")) == saved_against
    # Harwick (Red) saved Vane's shot at 67' (m08).
    assert SUMMARY["by_half"]["second_half"]["london_red"]["saves"] >= 1


def test_threat_matches_key_moments_definition():
    events = ms.load(ms.DATA_DIR / "match_xt.csv")
    red = sum(ms.threat(e) for e in events if e["team"] == "london_red" and e["period"] == 1)
    assert SUMMARY["by_half"]["first_half"]["london_red"]["threat_created"] == round(red, 4)


def test_moment_ids_in_order():
    moments = json.loads((ROOT / "data" / "key_moments.json").read_text())["moments"]
    assert SUMMARY["moment_ids"] == [m["id"] for m in moments]


def test_saved_file_is_up_to_date():
    saved = json.loads((ROOT / "data" / "match_summary.json").read_text())
    assert saved == json.loads(json.dumps(SUMMARY))


def test_thirds_use_the_documented_edges():
    assert ms.third(66.7) == "final" and ms.third(66.6) == "middle"
    assert ms.third(33.4) == "middle" and ms.third(33.3) == "defensive"


def test_final_third_entry():
    assert ms.final_third_entry(ev("pass", 60, 50, 70, 50))
    assert not ms.final_third_entry(ev("pass", 60, 50, 70, 50, "incomplete"))
    assert not ms.final_third_entry(ev("pass", 70, 50, 80, 50))  # already in it


def test_penalty_area_entry():
    assert ms.penalty_area_entry(ev("carry", 80, 50, 88, 50))
    assert not ms.penalty_area_entry(ev("pass", 80, 10, 90, 15))  # wide of the box
    assert not ms.penalty_area_entry(ev("pass", 85, 50, 90, 50))  # already in it


def test_progressive_action():
    assert ms.progressive(ev("pass", 10, 50, 40, 50))       # 31.5 m in own half
    assert not ms.progressive(ev("pass", 10, 50, 35, 50))   # 26.3 m: not enough in own half
    assert ms.progressive(ev("pass", 40, 50, 55, 50))       # 15.8 m into the other half
    assert ms.progressive(ev("carry", 60, 50, 70, 50))      # 10.5 m in the other half
    assert not ms.progressive(ev("pass", 60, 50, 60, 10))   # sideways
    assert not ms.progressive(ev("pass", 10, 50, 40, 50, "incomplete"))


def test_possession_lost_in_final_third():
    assert ms.possession_lost_in_final_third(ev("pass", 70, 50, 90, 50, "incomplete"))
    assert ms.possession_lost_in_final_third(ev("carry", 75, 50, 78, 50, "lost"))
    assert not ms.possession_lost_in_final_third(ev("pass", 60, 50, 90, 50, "incomplete"))  # started in the middle third
    assert not ms.possession_lost_in_final_third(ev("pass", 70, 50, 90, 50))
