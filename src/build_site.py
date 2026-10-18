"""Build web/data/ for the static page (web/index.html). No model calls.

Reads the frozen data (never changes it): data/match_xt.csv,
data/key_moments.json, data/narrations.json, data/analysis.json,
data/match_summary.json, data/player_summaries.json and
data/personalized/*.json. First runs the three verifiers on the saved text
(src/verify_narrations.py, run_analyst.py --verify, run_personalizer.py
--verify) and refuses to build if any of them fails, so the page only ever
shows text that passes every check as it is saved now.

Writes compact JSON to web/data/:
- match.json            teams, final score, result line, goals, the playback timeline
- events.json           every event as a row: columns + rows
- threat.json           threat created per 5-minute block per team (the blocks
                        of src/key_moments.py: completed passes and carries)
- key_moments.json      the moments, each with its playback time
- narrations.json       the Narrator's checked headline and explanation per moment
- analysis.json         the Analyst's match headline, story arc, turning point, phase notes
- player_summaries.json per-player facts
- profiles.json         the pre-generated Personalizer profiles: moment texts and recap
- overlays.json         timed, machine-readable overlay entries per profile
- meta.json             what was checked, and which languages exist

Playback timeline: one continuous clock in seconds. The first half runs
from 0:00 to the end of its last event's minute (47:00); the second half
starts again at 45:00 and runs to the end of its last event's minute. A
match time (period, minute, second) maps to timeline seconds with
timeline_seconds().

Run:  python src/build_site.py
"""

import json
import math
import sys
from pathlib import Path

import key_moments
import player_summary
import run_analyst
import run_personalizer
import verify_narrations

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT_DIR = ROOT / "web" / "data"

EVENT_COLUMNS = ["t", "period", "minute", "second", "team", "player", "type", "outcome", "x", "y", "xt_added"]

# Overlay reading time, in match-clock seconds at 1x: about 2.5 words a second.
OVERLAY_WORDS_PER_SECOND = 2.5
OVERLAY_MIN_SECONDS = 6
OVERLAY_MAX_SECONDS = 20

LANGUAGE_NAMES = {"en": "English", "ar": "العربية"}


def _read(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


# ------------------------------------------------------------ timeline

def periods(events) -> list:
    """[{period, start_minute, end_minute, offset}]: match minutes covered
    and where the period starts on the timeline (seconds)."""
    out, offset = [], 0
    for p in sorted({e["period"] for e in events}):
        es = [e for e in events if e["period"] == p]
        start = 0 if p == 1 else 45
        end = es[-1]["minute"] + 1
        out.append({"period": p, "start_minute": start, "end_minute": end, "offset": offset})
        offset += (end - start) * 60
    return out


def timeline_seconds(timeline, period, minute, second=0) -> int:
    p = next(x for x in timeline if x["period"] == period)
    return p["offset"] + (minute - p["start_minute"]) * 60 + second


def timeline_length(timeline) -> int:
    last = timeline[-1]
    return last["offset"] + (last["end_minute"] - last["start_minute"]) * 60


# ------------------------------------------------------------ data files

def events_file(events, timeline) -> dict:
    rows = [[timeline_seconds(timeline, e["period"], e["minute"], e["second"]), e["period"], e["minute"],
             e["second"], e["team"], e["player"], e["type"], e["outcome"], e["start_x"], e["start_y"],
             e["xt_added"]] for e in events]
    return {"columns": EVENT_COLUMNS, "rows": rows}


def threat_file(events, timeline) -> dict:
    """Threat per block per team, as in key_moments.momentum_shifts(). A
    block's end is the next block's start, or its period's end."""
    out = []
    for period, start, es in key_moments.blocks(events):
        p = next(x for x in timeline if x["period"] == period)
        end_minute = min(start + key_moments.BLOCK_MINUTES, p["end_minute"])
        if period == 1 and start < 45 <= start + key_moments.BLOCK_MINUTES:
            end_minute = 45  # first-half stoppage has its own block
        label = f"{start}+" if (period == 1 and start >= 45) or start >= 90 else f"{start}-{start + 5}"
        out.append({"period": period, "start_minute": start, "label": label,
                    "t_start": timeline_seconds(timeline, period, start),
                    "t_end": timeline_seconds(timeline, period, end_minute),
                    **{team: round(sum(key_moments.threat(e) for e in es if e["team"] == team), 4)
                       for team in key_moments.TEAMS}})
    return {"block_minutes": key_moments.BLOCK_MINUTES,
            "definition": "xT added by completed passes and carries", "blocks": out}


def spell_end(moment, events, timeline) -> int:
    """Timeline seconds of the last event of a momentum shift's run."""
    f = moment["facts"]
    last = [e for e in events if e["period"] == f["end_period"] and e["minute"] <= f["last_minute"]][-1]
    return timeline_seconds(timeline, last["period"], last["minute"], last["second"])


def moments_file(moments, events, timeline) -> list:
    """Each moment with t (its own time) and reveal_t: when the page may show
    it. A momentum shift describes a whole spell, so it is revealed when the
    spell ends; anything else at its own time."""
    out = []
    for m in moments:
        t = timeline_seconds(timeline, m["period"], m["minute"], m["second"])
        reveal = spell_end(m, events, timeline) if m["category"] == "momentum_shift" else t
        out.append({"id": m["id"], "category": m["category"], "tags": m["tags"], "period": m["period"],
                    "minute": m["minute"], "second": m["second"], "t": t, "reveal_t": reveal,
                    "team": m["team"], "players": m["players"],
                    **({"spell": {"start_minute": m["facts"]["start_minute"],
                                  "last_minute": m["facts"]["last_minute"]}}
                       if m["category"] == "momentum_shift" else {})})
    return out


def profile_label(profile: dict, teams: dict) -> str:
    if profile["focus_player"] != "none":
        return f"Follow {profile['focus_player']}"
    if profile["favourite_team"] != "none":
        return f"{teams[profile['favourite_team']].split()[-1]} fan"
    return "Analyst" if profile["mode"] == "analyst" else "Fan"


def profiles_file(docs, teams) -> list:
    return [{"key": d["profile_key"], "label": profile_label(d["profile"], teams), "profile": d["profile"],
             "selection": d["selection"], "player": d["player"],
             "moments": [{"id": e["id"], "involves_favourite": e["involves_favourite"], **e["output"]}
                         for e in d["moments"]],
             "recap": d["recap"]["output"]["lines"]} for d in docs]


def display_headline(text: str) -> str:
    """A headline as shown on screen: no trailing full stop."""
    return text[:-1] if text.endswith(".") and not text.endswith("..") else text


def overlay_duration(headline: str, lines: list) -> int:
    words = len(" ".join([headline, *lines]).split())
    return max(OVERLAY_MIN_SECONDS, min(OVERLAY_MAX_SECONDS, math.ceil(words / OVERLAY_WORDS_PER_SECOND)))


def overlays_file(profiles, moments, timeline) -> dict:
    by_id = {m["id"]: m for m in moments}
    entries = []
    for p in profiles:
        for e in p["moments"]:
            m = by_id[e["id"]]
            entries.append({"profile_key": p["key"], "moment_id": e["id"], "start_seconds": m["reveal_t"],
                            "duration_seconds": overlay_duration(e["headline"], e["lines"]),
                            "type": m["category"], "headline": display_headline(e["headline"]),
                            "lines": e["lines"]})
    entries.sort(key=lambda x: (x["profile_key"], x["start_seconds"], x["moment_id"]))
    return {"clock": "start_seconds is on the playback timeline in match.json: the first half from 0, "
                     "the second half from its offset; duration_seconds is at 1x speed",
            "overlays": entries}


# ------------------------------------------------------------ checks

def run_checks() -> dict:
    """The verifiers on the saved text as it is now. No model calls."""
    moments = _read("key_moments.json")["moments"]
    narrations = {n["id"]: n for n in _read("narrations.json")["narrations"]}
    narr = verify_narrations.verify(moments, narrations)
    analysis_ok, analysis_lines = run_analyst.verify(run_analyst.load_inputs(), run_analyst.load_cache())
    pdata = run_personalizer.load_data()
    personalized = {path.stem: run_personalizer.verify(path, pdata)
                    for path in sorted(run_personalizer.OUT_DIR.glob("*.json"))}
    failures = ([f"narration {r[0]}: {line}" for r in narr if not r[1] for line in r[3] or ["failed"]]
                + ([f"analysis: {line}" for line in analysis_lines] if not analysis_ok else [])
                + [f"{key}: {line}" for key, (ok, lines) in personalized.items() if not ok for line in lines])
    return {"passed": not failures, "failures": failures,
            "narrations": {r[0]: r[1] for r in narr}, "analysis": analysis_ok,
            "personalized": {key: ok for key, (ok, _) in personalized.items()}}


# ------------------------------------------------------------ build

def build(checks: dict) -> dict:
    """{file name: content} for web/data/."""
    events = key_moments.load(DATA / "match_xt.csv")
    timeline = periods(events)
    summary = _read("match_summary.json")
    moments = moments_file(_read("key_moments.json")["moments"], events, timeline)
    narrations = {n["id"]: {"headline": n["narration"]["headline"], "explanation": n["narration"]["explanation"]}
                  for n in _read("narrations.json")["narrations"] if n["status"] == "ok"}
    analysis = _read("analysis.json")["analysis"]
    players = _read("player_summaries.json")
    if players != json.loads(json.dumps(player_summary.build())):
        sys.exit("data/player_summaries.json is out of date: run python src/player_summary.py")
    docs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((DATA / "personalized").glob("*.json"))]
    order = {"analyst": 0, "london_red": 1, "london_blue": 2}
    docs.sort(key=lambda d: (order.get(d["profile"]["mode"] if d["profile"]["mode"] == "analyst"
                                       else d["profile"]["favourite_team"], 3), d["profile_key"]))
    profiles = profiles_file(docs, summary["teams"])
    languages = sorted({p["profile"]["language"] for p in profiles})

    return {
        "match.json": {"teams": summary["teams"], "final_score": summary["final_score"],
                       "result_line": summary["result_line"], "goals": summary["goals"],
                       "timeline": {"periods": timeline, "length_seconds": timeline_length(timeline)}},
        "events.json": events_file(events, timeline),
        "threat.json": threat_file(events, timeline),
        "key_moments.json": {"moments": moments},
        "narrations.json": narrations,
        "analysis.json": analysis,
        "player_summaries.json": players,
        "profiles.json": {"profiles": profiles},
        "overlays.json": overlays_file(profiles, moments, timeline),
        "meta.json": {"synthetic": True, "checks": checks,
                      "languages": [{"code": c, "name": LANGUAGE_NAMES.get(c, c), "available": c in languages}
                                    for c in ("en", "ar")]},
    }


def dumps(content) -> str:
    return json.dumps(content, ensure_ascii=False, separators=(",", ":")) + "\n"


def main() -> int:
    checks = run_checks()
    if not checks["passed"]:
        print("Not building: saved text fails its checks")
        for line in checks["failures"]:
            print(f"    {line}")
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in build(checks).items():
        (OUT_DIR / name).write_text(dumps(content), encoding="utf-8")
        print(f"Wrote web/data/{name} ({(OUT_DIR / name).stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
