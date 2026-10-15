"""Check data/match.json against the docs.

The rules are read from the docs themselves, not copied from the generator:
- docs/data-format.md: event fields and types, allowed outcomes per type
- docs/teams.md:       every team's name/shirt pairs
- docs/match-story.md: the final score

Run:  python src/validate_match.py [path/to/match.json]
Exits with code 1 if any check fails.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
MAX_ERRORS_SHOWN = 5


# ------------------------------------------------------------ reading the docs

def section(text, heading):
    """The text under a '## heading', up to the next '## '."""
    m = re.search(rf"^## {re.escape(heading)}.*?$(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not m:
        raise ValueError(f"heading '## {heading}' not found")
    return m.group(1)


def table_rows(text):
    """Cells of each markdown table row, skipping the header and separator."""
    rows = [line for line in text.splitlines() if line.strip().startswith("|")]
    return [[c.strip() for c in row.strip().strip("|").split("|")] for row in rows[2:]]


def read_fields():
    """{field: type} from the 'Event fields' table."""
    text = (DOCS / "data-format.md").read_text(encoding="utf-8")
    fields = {}
    for cells in table_rows(section(text, "Event fields")):
        for name in re.findall(r"`(\w+)`", cells[0]):
            fields[name] = cells[1]
    return fields


def read_outcomes():
    """{type: set of allowed outcomes} from 'Allowed outcomes for each type'."""
    text = (DOCS / "data-format.md").read_text(encoding="utf-8")
    return {
        re.findall(r"`(\w+)`", cells[0])[0]: set(re.findall(r"`(\w+)`", cells[1]))
        for cells in table_rows(section(text, "Allowed outcomes for each type"))
    }


def read_squads():
    """{team: {shirt: name}} from teams.md."""
    text = (DOCS / "teams.md").read_text(encoding="utf-8")
    squads = {}
    for m in re.finditer(r"^## .*?\(`(\w+)`\)", text, re.M):
        body = text[m.end():].split("\n## ")[0]
        squads[m.group(1)] = {int(c[0]): c[1] for c in table_rows(body)}
    return squads


def read_story_score():
    """{team: goals} from the bold score line in match-story.md."""
    text = (DOCS / "match-story.md").read_text(encoding="utf-8")
    m = re.search(r"\*\*London Red (\d+)\s*[–-]\s*(\d+) London Blue\*\*", text)
    if not m:
        raise ValueError("final score line not found in match-story.md")
    return {"london_red": int(m.group(1)), "london_blue": int(m.group(2))}


# --------------------------------------------------------------------- checks

def type_ok(value, kind):
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "string":
        return isinstance(value, str)
    if kind == "bool":
        return isinstance(value, bool)
    raise ValueError(f"unknown field type in data-format.md: {kind}")


def label(e):
    return (f"event {e.get('event_id', '?')} ({e.get('period', '?')}:"
            f"{e.get('minute', '?')}:{e.get('second', '?')})")


def check_fields(events, fields):
    errors = []
    for e in events:
        missing = [f for f in fields if f not in e]
        extra = [f for f in e if f not in fields]
        if missing:
            errors.append(f"{label(e)}: missing {missing}")
        if extra:
            errors.append(f"{label(e)}: unexpected fields {extra}")
        for f, kind in fields.items():
            if f in e and not type_ok(e[f], kind):
                errors.append(f"{label(e)}: {f}={e[f]!r} is not {kind}")
    return errors


def check_outcomes(events, outcomes):
    errors = []
    for e in events:
        t = e.get("type")
        if t not in outcomes:
            errors.append(f"{label(e)}: unknown type {t!r}")
        elif e.get("outcome") not in outcomes[t]:
            errors.append(f"{label(e)}: outcome {e.get('outcome')!r} not allowed "
                          f"for {t} (allowed: {sorted(outcomes[t])})")
    return errors


def check_coordinates(events):
    errors = []
    for e in events:
        for f in ("start_x", "start_y", "end_x", "end_y"):
            v = e.get(f)
            if not isinstance(v, (int, float)) or not 0 <= v <= 100:
                errors.append(f"{label(e)}: {f}={v!r} is outside 0-100")
            elif round(v, 1) != v:
                errors.append(f"{label(e)}: {f}={v!r} has more than one decimal place")
        if e.get("type") in ("tackle", "interception", "foul") and \
                (e.get("end_x"), e.get("end_y")) != (e.get("start_x"), e.get("start_y")):
            errors.append(f"{label(e)}: {e['type']} must end where it starts")
        if e.get("type") == "shot" and e.get("outcome") in ("goal", "off_target") \
                and e.get("end_x") != 100:
            errors.append(f"{label(e)}: {e['outcome']} shot must end at end_x = 100")
    return errors


def check_order(events):
    errors = []
    prev = None
    for i, e in enumerate(events, start=1):
        if e.get("event_id") != i:
            errors.append(f"{label(e)}: event_id should be {i}")
        if e.get("period") not in (1, 2):
            errors.append(f"{label(e)}: period must be 1 or 2")
        if not 0 <= e.get("second", -1) <= 59:
            errors.append(f"{label(e)}: second must be 0-59")
        if e.get("period") == 2 and e.get("minute", 0) < 45:
            errors.append(f"{label(e)}: second half starts at minute 45")
        key = (e.get("period"), e.get("minute"), e.get("second"))
        if prev and key < prev[0]:
            errors.append(f"{label(e)}: comes before {label(prev[1])}")
        if prev and e.get("possession_id", 0) < prev[1].get("possession_id", 0):
            errors.append(f"{label(e)}: possession_id goes backwards")
        prev = (key, e)
    return errors


def check_players(events, squads):
    errors = []
    for e in events:
        team, shirt, name = e.get("team"), e.get("shirt_number"), e.get("player")
        if team not in squads:
            errors.append(f"{label(e)}: unknown team {team!r}")
        elif shirt not in squads[team]:
            errors.append(f"{label(e)}: {team} has no shirt number {shirt}")
        elif squads[team][shirt] != name:
            errors.append(f"{label(e)}: {team} #{shirt} is {squads[team][shirt]!r}, "
                          f"not {name!r}")
    return errors


def check_score(events, match, story_score):
    goals = {team: 0 for team in story_score}
    for e in events:
        if e.get("type") == "shot" and e.get("outcome") == "goal":
            goals[e["team"]] = goals.get(e["team"], 0) + 1
    errors = []
    if goals != story_score:
        errors.append(f"goals in the data {goals} != match-story.md score {story_score}")
    if match.get("final_score") != story_score:
        errors.append(f"match.final_score {match.get('final_score')} != "
                      f"match-story.md score {story_score}")
    return errors, goals


def check_assists(events):
    """data-format.md rule 2: an assist is a complete pass straight before a
    goal, by the same team, in the same possession."""
    errors = []
    for i, e in enumerate(events):
        if not e.get("is_assist"):
            continue
        nxt = events[i + 1] if i + 1 < len(events) else {}
        if e.get("type") != "pass" or e.get("outcome") != "complete":
            errors.append(f"{label(e)}: is_assist on a {e.get('type')} "
                          f"({e.get('outcome')}), must be a complete pass")
        elif not (nxt.get("type") == "shot" and nxt.get("outcome") == "goal"
                  and nxt.get("team") == e.get("team")
                  and nxt.get("possession_id") == e.get("possession_id")):
            errors.append(f"{label(e)}: assist is not followed by a goal in the "
                          f"same possession")
    return errors


def check_pass_chain(events):
    """data-format.md rule 3: a complete pass ends where the same team's next
    event in that possession starts."""
    errors = []
    for i, e in enumerate(events):
        if e.get("type") != "pass" or e.get("outcome") != "complete":
            continue
        for nxt in events[i + 1:]:
            if nxt.get("possession_id") != e.get("possession_id"):
                break
            if nxt.get("team") == e.get("team"):
                if (nxt["start_x"], nxt["start_y"]) != (e["end_x"], e["end_y"]):
                    errors.append(f"{label(e)}: pass ends at ({e['end_x']}, {e['end_y']}) "
                                  f"but {label(nxt)} starts at "
                                  f"({nxt['start_x']}, {nxt['start_y']})")
                break
    return errors


# ----------------------------------------------------------------------- main

def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "match.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    match, events = data.get("match", {}), data.get("events", [])
    story_score = read_story_score()
    score_errors, goals = check_score(events, match, story_score)

    checks = [
        ("All fields present, with the right types", check_fields(events, read_fields())),
        ("Allowed outcome for each type", check_outcomes(events, read_outcomes())),
        ("Coordinates within 0-100", check_coordinates(events)),
        ("Events in time order", check_order(events)),
        ("Name/shirt pairs match teams.md", check_players(events, read_squads())),
        ("Goals add up to the final score", score_errors),
        ("Assists come straight before their goal", check_assists(events)),
        ("Complete passes end where the next touch starts", check_pass_chain(events)),
    ]

    print(f"Validating {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}: "
          f"{len(events)} events\n")
    failed = 0
    for name, errors in checks:
        print(f"  [{'PASS' if not errors else 'FAIL'}] {name}")
        for err in errors[:MAX_ERRORS_SHOWN]:
            print(f"         - {err}")
        if len(errors) > MAX_ERRORS_SHOWN:
            print(f"         ... and {len(errors) - MAX_ERRORS_SHOWN} more")
        failed += bool(errors)

    print(f"\n  Goals in the data: London Red {goals.get('london_red', 0)} - "
          f"{goals.get('london_blue', 0)} London Blue "
          f"(match-story.md: {story_score['london_red']} - {story_score['london_blue']})")
    if failed:
        print(f"\nRESULT: FAIL ({failed} of {len(checks)} checks failed)")
        sys.exit(1)
    print(f"\nRESULT: PASS (all {len(checks)} checks passed)")


if __name__ == "__main__":
    main()
