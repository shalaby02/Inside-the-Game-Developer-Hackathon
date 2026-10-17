"""Analyst agent: reads the whole match and decides how its story is told.

Same pattern as src/narrator.py: INSTRUCTIONS (system prompt), OUTPUT_SCHEMA
and the Narrator's MODEL_PARAMS, one direct Chat Completions call to the
deployed Foundry model. Its input is data/key_moments.json (through
narrator.moment_input, so raw coordinates stay hidden) and
data/match_summary.json. It never sees data/narrations.json.

It returns match_headline, story_arc, turning_point, phase_notes and
moment_priority (see OUTPUT_SCHEMA). Every answer is checked in code:
- structure: ids exist, each once in story_arc, story_arc in match order,
  exactly one turning point (the same one in story_arc and turning_point),
  and it is a goal that changed the score state or a momentum shift (a
  change in the threat balance), every goal and the turning point essential,
  3-5 phase notes with cites that exist and one of them citing
  first_half_summary, result_line quoted word for word, the headline naming
  the final score and the winning team, the turning point's reason quoting
  an xT number from its moment.
- grounding (src/grounding.py), scoped to what each text describes: a
  phase note only against the facts it cites, the turning point's reason
  against its moment plus the score and goal timeline, the headline
  against all the input.
- style (src/style_check.py, plus style_rules.CONNECTORS in the headline
  and phase notes), polish (src/polish_check.py) and term backing
  (src/term_check.py) on the same texts. Term backing is per sentence: a
  sentence's subject is what it names (a moment's minute, player, xT number
  or quoted phrase; a summary stat's number), drawn from the note's cites,
  from the whole input for the headline, and always the turning point's own
  moment for its reason.
On a failure the model gets the failures and tries again, up to MAX_RETRIES
times; after that the analysis is marked failed and kept for inspection only.

Use:  from analyst import analyse, analyst_input;  analyse(client, deployment, analyst_input(km, summary))
"""

import json
import re
from decimal import Decimal

import grounding
import polish_check
import style_check
import term_check
from narrator import MODEL_PARAMS, _borrows, moment_input, sentences
from style_rules import ANALYST_PROMPT_RULES, CONNECTORS, PROMPT_RULES

MAX_RETRIES = 2
ROLES = ["opening", "build_up", "turning_point", "response", "decider", "other"]
MIN_NOTES, MAX_NOTES = 3, 5
MAX_NOTE_SENTENCES = 2

# Moment facts that are xT values; the turning point's reason must quote one.
XT_FACTS = {"xt_added", "zone_start_value", "zone_end_value", "key_pass_xt_added", "shot_zone_value",
            "team_threat", "opponent_threat", "team_threat_before", "opponent_threat_before",
            "top_player_threat"}
# What the turning point's reason may use besides its own moment: the score and the clock.
REASON_SUMMARY_KEYS = ("teams", "final_score", "result_line", "goals", "leads", "momentum_runs")
# Categories that can be the turning point: a goal that changed the score state,
# or a momentum shift (by definition a change in the threat balance).
TURNING_POINT_CATEGORIES = {"goal", "momentum_shift"}
# Who a moment is about (see narrator.moment_input).
PEOPLE_KEYS = ("scorer", "key_passer", "goalkeeper", "shooter", "player", "receiver", "top_threat_creators")
QUOTABLE_FACTS = ("build_up", "counter_label", "score_effect")
CONNECTOR_RULES = [(pattern, f'"{word}" {why}; state the facts side by side')
                   for word, pattern, why in CONNECTORS]
# Analysis words that may start a sentence; grounding would otherwise read them as names.
TERM_WORDS = ["Final-third", "Final", "Middle", "Defensive", "Penalty-area", "Penalty", "Progressive",
              "Possessions", "Transition", "Transitions", "Counter-attack", "Build-up",
              "Shot-location", "Entries"]
# A moment id ("m09") or a cite path ("summary.by_half") written into the text.
_ID_IN_TEXT = re.compile(r"\bm\d{2}\b|\bsummary\.\w+", re.I)
_ORDINAL = re.compile(r"(?<![\d.])(\d+)(?:st|nd|rd|th)\b")
_SCORE = re.compile(r"(?<![\d.])\d+[-–]\d+(?![\d.])")
_NUM = re.compile(r"(?<![\d.])\d+(?:\.\d+)?")

INSTRUCTIONS = f"""\
You are the Analyst for a football match recap: a performance analyst who reads the whole match and decides how its story is told.

xT (expected threat) is how likely a team is to score soon from where it has the ball. Every spot on the pitch has an xT value; "xT added" is how much a pass or carry raised it. "Threat created" is the xT a team added with its completed passes and carries.

You get one JSON object:
- moments: the key moments in match order. Each has an id (m01, m02, ...), category, tags, period, minute, second, team, opponent, the players by role, and facts.
- summary: whole-match facts computed in code: teams (display names), final_score, result_line (the result in words), goals (moment_id, minute, second, team, scorer, score_after), leads (team, from_minute/from_second, and to_minute/to_second when the lead ended at a goal; ends_at "full_time" means it lasted to the end, which has no recorded time), minutes_led (null for a lead to full time: never give its length), first_half_summary (each team's threat_created, shots and goals in the first half), by_half (first_half and second_half, each team's threat_created, final_third_entries, penalty_area_entries, progressive_actions, possessions_lost_in_final_third, shots and saves), momentum_runs (each momentum shift's goals_in_run: the goals scored during it), and moment_ids. Team keys such as london_red are ids: write the team as summary.teams gives it ("London Red").

Definitions (computed in code; never recompute them):
- final third: the third of the pitch nearest the goal a team attacks. A final-third entry is a completed pass or carry from outside it into it.
- penalty-area entry: a completed pass or carry from outside the penalty area into it.
- progressive action: a completed pass or carry that moves the ball at least 30 metres closer to goal within a team's own half, 15 metres from its own half into the other half, or 10 metres within the other half.
- possession lost in the final third: an incomplete pass or lost carry that starts in the final third.
- saves: shots by the other team that this team's goalkeeper saved.
- transition: a move tagged counter: it starts in the team's own half and reaches a shot within 15 seconds.
- build-up phase: how one possession reached its key action, as its build_up fact says.

Return:
- match_headline: one sentence that sums up the match. It must contain the final score and the winning team; the simplest way is to quote result_line word for word.
- story_arc: the moments that tell the story, in match order, each at most once, as {{moment_id, role}}. Roles: opening (how the match was set up; at most one, and first), build_up (moments that led to the turning point), turning_point (exactly one: where the match turned), response (what came after the turning point), decider (at most one, a goal: the goal that settled the result), other.
- turning_point: {{moment_id, reason}}: the same moment as the arc's turning_point, and one sentence on why it was the turning point that quotes at least one xT number from that moment's facts. It must be a goal that changed the score state (level to a lead, or a lead to level) or a momentum shift (a change in the threat balance). Choose the first goal that changed the score state toward the result in result_line; first_half_summary shows whether threat alone had changed the score before. Use a momentum shift only if no goal did that.
- phase_notes: {MIN_NOTES} to {MAX_NOTES} short analyst observations, at most {MAX_NOTE_SENTENCES} sentences each. Each has text and cites: the facts the text uses, as paths, e.g. "m09.team_threat" for a moment fact or "summary.by_half.second_half.london_red.final_third_entries" for a summary fact. Every number and minute in the text must be in a fact it cites, and every analysis term needs its backing fact cited. Make each note one clear point that compares teams, halves or spells. At least one note cites summary.first_half_summary, and result_line is quoted word for word in the headline or a note.
- moment_priority: {{essential, supporting}}: essential = moments any recap must include (every goal and the turning point, all of them in story_arc); supporting = useful but optional. No id in both lists.

Wording:
- Speak as a performance analyst: final third, final-third entries, penalty-area entries, transition, build-up phase, progressive actions, threat created, quoting the xT numbers from the facts.
- Use only the ids, names, numbers and minutes in the input. Quote numbers exactly as given. No differences, ratios, totals or percentages of your own.
- Say a minute as the ordinal of a minute field, such as "the 61st minute"; a spell as "from the 61st minute to the 74th minute".
- You see the whole match, but these rules still apply to the text: no "winner", "decisive", "comeback", "kept" or "held"; compare teams and halves only with the numbers, never with best, biggest, clearest or greatest.
{PROMPT_RULES}
{ANALYST_PROMPT_RULES}
- Ids (m01) and paths appear only in moment_id, story_arc, moment_priority and cites, never in match_headline, reason or text.

Return only the JSON object."""

OUTPUT_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "analysis",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "match_headline": {"type": "string"},
                "story_arc": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"moment_id": {"type": "string"}, "role": {"type": "string", "enum": ROLES}},
                    "required": ["moment_id", "role"], "additionalProperties": False}},
                "turning_point": {
                    "type": "object",
                    "properties": {"moment_id": {"type": "string"}, "reason": {"type": "string"}},
                    "required": ["moment_id", "reason"], "additionalProperties": False},
                "phase_notes": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"text": {"type": "string"},
                                   "cites": {"type": "array", "items": {"type": "string"}}},
                    "required": ["text", "cites"], "additionalProperties": False}},
                "moment_priority": {
                    "type": "object",
                    "properties": {"essential": {"type": "array", "items": {"type": "string"}},
                                   "supporting": {"type": "array", "items": {"type": "string"}}},
                    "required": ["essential", "supporting"], "additionalProperties": False},
            },
            "required": ["match_headline", "story_arc", "turning_point", "phase_notes", "moment_priority"],
            "additionalProperties": False,
        },
    },
}


def analyst_input(key_moments: dict, summary: dict) -> dict:
    """The object the model sees, and that every check runs against."""
    return {"moments": [{"id": m["id"], **moment_input(m)} for m in key_moments["moments"]],
            "summary": summary}


def _moments(inputs: dict) -> dict:
    return {m["id"]: m for m in inputs["moments"]}


def resolve(path: str, inputs: dict):
    """(value, last key) for a cite such as "m09.team_threat" (a moment fact,
    with or without ".facts") or "summary.by_half.first_half.london_red.shots";
    None if the path doesn't exist."""
    if not isinstance(path, str) or not path:
        return None
    head, *rest = path.split(".")
    if head == "summary":
        node = inputs["summary"]
    else:
        node = _moments(inputs).get(head)
        if node is None:
            return None
        if rest and rest[0] not in node and rest[0] in node["facts"]:
            node = node["facts"]
    for part in rest:
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return None
    return node, (rest[-1] if rest else head)


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def _dec(x) -> Decimal:
    return abs(Decimal(str(x)).normalize())


# ------------------------------------------------------------ what each text describes

def texts(analysis: dict, inputs: dict) -> list:
    """Every prose field with its scope: [{"where", "text", "facts" (grounding),
    "subject" (term backing), "style_facts", "moment_rules", "sentence"}]."""
    moments = _moments(inputs)
    out = [{"where": "match_headline", "text": analysis["match_headline"], "facts": inputs,
            "candidates": (inputs["moments"], list(_leaves(inputs["summary"]))),
            "style_facts": inputs, "moment_rules": False, "sentence": False, "connectors": True}]

    tp = moments.get(analysis["turning_point"]["moment_id"])
    if tp:
        out.append({"where": "turning_point.reason", "text": analysis["turning_point"]["reason"],
                    "facts": [tp, {k: inputs["summary"][k] for k in REASON_SUMMARY_KEYS}],
                    "subject": term_check.subject([tp]), "style_facts": tp, "moment_rules": True,
                    "sentence": True, "connectors": False})

    for i, note in enumerate(analysis["phase_notes"]):
        cited, cited_moments, leaves = [], {}, []
        for cite in note["cites"]:
            found = resolve(cite, inputs)
            if found is None:
                continue
            value, key = found
            cited.append({key: value})
            head = cite.split(".")[0]
            if head == "summary":
                leaves += _leaves(value, key)
            else:
                cited_moments[head] = moments[head]
        out.append({"where": f"phase_notes[{i}]", "text": note["text"], "facts": cited,
                    "candidates": (list(cited_moments.values()), leaves),
                    "style_facts": {"moments": list(cited_moments.values())}, "moment_rules": False,
                    "sentence": True, "connectors": True})
    return out


def _leaves(obj, key=None):
    """(key, number) for every number in a summary subtree."""
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        yield key, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _leaves(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _leaves(v, key)


def _stat_numbers(sentence):
    """Numbers that can point at a stat or an xT value: minutes ("61st") and scores ("2-1") left out."""
    return {_dec(n) for n in _NUM.findall(_SCORE.sub(" ", _ORDINAL.sub(" ", sentence)))}


def _names_moment(sentence, moment):
    """The sentence names this moment: its minute, a player's full name, one of
    its decimal (xT) numbers, or a quoted fact phrase."""
    facts = moment["facts"]
    minutes = {moment["minute"]} | {v for k, v in facts.items() if k.endswith("_minute")}
    if {int(n) for n in _ORDINAL.findall(sentence)} & minutes:
        return True
    people = [moment.get(k) for k in PEOPLE_KEYS]
    names = [n for p in people for n in (p if isinstance(p, list) else [p]) if n]
    if any(n in sentence for n in names):
        return True
    decimals = {_dec(v) for v in facts.values() if isinstance(v, float) and v != int(v)}
    if decimals & _stat_numbers(sentence):
        return True
    return any(facts.get(k) and _borrows(sentence, facts[k]) for k in QUOTABLE_FACTS)


def sentence_subject(sentence, candidates):
    """What one sentence is about, for term backing: the candidate moments it
    names, and the summary stats whose number it gives."""
    moments, leaves = candidates
    numbers = _stat_numbers(sentence)
    return term_check.subject([m for m in moments if _names_moment(sentence, m)],
                              {k for k, v in leaves if k and _dec(v) in numbers})


def term_items(items):
    """(where, sentence, subject) for the term check, one per sentence."""
    out = []
    for t in items:
        if "subject" in t:
            out.append((t["where"], t["text"], t["subject"]))
        else:
            out += [(t["where"], s, sentence_subject(s, t["candidates"])) for s in sentences(t["text"])]
    return out


# ------------------------------------------------------------ checks

def shape_problems(analysis) -> list:
    if not isinstance(analysis, dict):
        return ["response is not a JSON object"]
    problems = []
    if not isinstance(analysis.get("match_headline"), str) or not analysis["match_headline"].strip():
        problems.append("match_headline is missing or empty")
    arc = analysis.get("story_arc")
    if not isinstance(arc, list) or not all(isinstance(a, dict) and isinstance(a.get("moment_id"), str)
                                            and isinstance(a.get("role"), str) for a in arc):
        problems.append("story_arc must be a list of {moment_id, role}")
    tp = analysis.get("turning_point")
    if not isinstance(tp, dict) or not isinstance(tp.get("moment_id"), str) or not isinstance(tp.get("reason"), str):
        problems.append("turning_point must be {moment_id, reason}")
    notes = analysis.get("phase_notes")
    if not isinstance(notes, list) or not all(isinstance(n, dict) and isinstance(n.get("text"), str)
                                              and isinstance(n.get("cites"), list) for n in notes):
        problems.append("phase_notes must be a list of {text, cites}")
    mp = analysis.get("moment_priority")
    if not isinstance(mp, dict) or not all(isinstance(mp.get(k), list) for k in ("essential", "supporting")):
        problems.append("moment_priority must be {essential, supporting}")
    return problems


def structure_problems(analysis: dict, inputs: dict) -> list:
    moments = _moments(inputs)
    order = {m["id"]: (m["period"], m["minute"], m["second"]) for m in inputs["moments"]}
    goals = [m["id"] for m in inputs["moments"] if m["category"] == "goal"]
    problems = []

    def unknown(ids, where):
        for i in ids:
            if i not in moments:
                problems.append(f'{where}: "{i}" is not a moment id')

    if len(sentences(analysis["match_headline"])) != 1:
        problems.append("match_headline must be one sentence")
    problems += headline_problems(analysis["match_headline"], inputs["summary"])
    result = inputs["summary"]["result_line"]
    if not any(result in t for t in [analysis["match_headline"]] + [n["text"] for n in analysis["phase_notes"]]):
        problems.append(f'quote result_line word for word in match_headline or a phase note: "{result}"')
    if not any(c.startswith("summary.first_half_summary") for n in analysis["phase_notes"] for c in n["cites"]):
        problems.append("at least one phase note must cite summary.first_half_summary")
    for t in texts(analysis, inputs):
        for m in _ID_IN_TEXT.finditer(t["text"]):
            problems.append(f'{t["where"]}: "{m.group(0)}" is an id or path; ids belong only in id fields and cites')

    # story_arc
    arc = analysis["story_arc"]
    arc_ids = [a["moment_id"] for a in arc]
    unknown(arc_ids, "story_arc")
    for i in sorted({i for i in arc_ids if arc_ids.count(i) > 1}):
        problems.append(f'story_arc: "{i}" appears more than once')
    known = [i for i in arc_ids if i in order]
    for a, b in zip(known, known[1:]):
        if order[a] > order[b]:
            problems.append(f"story_arc is not in match-time order: {a} comes before {b}")
    for a in arc:
        if a["role"] not in ROLES:
            problems.append(f'story_arc: role "{a["role"]}" is not one of {", ".join(ROLES)}')
    turning = [a["moment_id"] for a in arc if a["role"] == "turning_point"]
    if len(turning) != 1:
        problems.append(f"story_arc must have exactly one turning_point role, has {len(turning)}")
    openings = [i for i, a in enumerate(arc) if a["role"] == "opening"]
    if len(openings) > 1 or openings and openings[0] != 0:
        problems.append("story_arc: opening must be used at most once, on the first entry")
    deciders = [a["moment_id"] for a in arc if a["role"] == "decider"]
    if len(deciders) > 1:
        problems.append("story_arc: decider must be used at most once")
    for i in deciders:
        if i in moments and moments[i]["category"] != "goal":
            problems.append(f"story_arc: decider {i} is not a goal")

    # turning_point
    tp = analysis["turning_point"]
    tp_id = tp["moment_id"]
    unknown([tp_id], "turning_point")
    if len(turning) == 1 and turning[0] != tp_id:
        problems.append(f"turning_point is {tp_id} but story_arc marks {turning[0]} as turning_point")
    if len(sentences(tp["reason"])) != 1:
        problems.append("turning_point.reason must be one sentence")
    if tp_id in moments:
        problems += turning_point_problems(moments[tp_id], inputs["summary"])
    if tp_id in moments:
        xt = {_dec(v) for k, v in moments[tp_id]["facts"].items() if k in XT_FACTS}
        quoted = {_dec(n) for n in re.findall(r"(?<![\d.])\d+\.\d+", tp["reason"])}
        if not xt & quoted:
            problems.append(f"turning_point.reason must quote an xT number from {tp_id}'s facts "
                            f"({', '.join(sorted(k for k in moments[tp_id]['facts'] if k in XT_FACTS))})")

    # phase_notes
    notes = analysis["phase_notes"]
    if not MIN_NOTES <= len(notes) <= MAX_NOTES:
        problems.append(f"phase_notes must have {MIN_NOTES} to {MAX_NOTES} notes, has {len(notes)}")
    for i, note in enumerate(notes):
        if len(sentences(note["text"])) > MAX_NOTE_SENTENCES:
            problems.append(f"phase_notes[{i}] has more than {MAX_NOTE_SENTENCES} sentences")
        if not note["cites"]:
            problems.append(f"phase_notes[{i}] cites no facts")
        for cite in note["cites"]:
            if resolve(cite, inputs) is None:
                problems.append(f'phase_notes[{i}] cites "{cite}", which is not a fact in the input')

    # moment_priority
    essential, supporting = analysis["moment_priority"]["essential"], analysis["moment_priority"]["supporting"]
    unknown(essential, "moment_priority.essential")
    unknown(supporting, "moment_priority.supporting")
    listed = essential + supporting
    for i in sorted({i for i in listed if listed.count(i) > 1}):
        problems.append(f'moment_priority: "{i}" is listed more than once')
    for g in goals:
        if g not in essential:
            problems.append(f"moment_priority: goal {g} must be essential")
    if tp_id in moments and tp_id not in essential:
        problems.append(f"moment_priority: the turning point {tp_id} must be essential")
    for i in essential:
        if i in moments and i not in arc_ids:
            problems.append(f"moment_priority: essential moment {i} is missing from story_arc")
    return problems


def headline_problems(headline: str, summary: dict) -> list:
    """The headline gives the final score and the winning team (both teams for a draw)."""
    final, names = summary["final_score"], summary["teams"]
    a, b = sorted(final, key=final.get, reverse=True)
    score = rf"(?<![\d.]){final[a]}\s*[-–]\s*{final[b]}(?![\d.])"
    problems = []
    if not re.search(score, headline):
        problems.append(f"match_headline must give the final score {final[a]}-{final[b]}")
    teams = [a, b] if final[a] == final[b] else [a]
    for t in teams:
        if names[t] not in headline:
            problems.append(f"match_headline must name {'both teams' if len(teams) == 2 else 'the winning team'}: {names[t]}")
    return problems


def _state(score: dict) -> int:
    a, b = sorted(score)
    return (score[a] > score[b]) - (score[a] < score[b])


def turning_point_problems(moment: dict, summary: dict) -> list:
    """The turning point changed the score state (a goal from level to a lead or
    from a lead to level) or the threat balance (a momentum shift)."""
    if moment["category"] not in TURNING_POINT_CATEGORIES:
        return [f"turning_point {moment['id']} is a {moment['category']}: it must be a goal that changed the "
                "score state or a momentum shift that changed the threat balance"]
    if moment["category"] == "goal":
        goals = summary["goals"]
        i = next((k for k, g in enumerate(goals) if g["moment_id"] == moment["id"]), None)
        before = goals[i - 1]["score_after"] if i else dict.fromkeys(summary["final_score"], 0)
        if i is not None and _state(before) == _state(goals[i]["score_after"]):
            return [f"turning_point {moment['id']} did not change the score state"]
    return []


def _merge(results) -> dict:
    """[(where, result)] -> one {"passed", "offending"} with each value prefixed by where."""
    offending = []
    for where, r in results:
        for o in r.offending:
            item = {**o, "value": o["value"] if o["value"].startswith(where) else f"{where}: {o['value']}"}
            if item not in offending:
                offending.append(item)
    return {"passed": not offending, "offending": offending}


def run_checks(analysis, inputs: dict) -> dict:
    """Every check on one analysis, no model calls. Returns {"passed",
    "format_problems", "grounding", "style", "polish", "terms"}."""
    problems = shape_problems(analysis)
    result = {"format_problems": problems, "grounding": None, "style": None, "polish": None, "terms": None}
    if problems:
        result["passed"] = False
        return result
    problems += structure_problems(analysis, inputs)

    names = list(_strings(inputs)) + TERM_WORDS
    items = texts(analysis, inputs)
    result["grounding"] = _merge((t["where"], grounding.check(t["text"], t["facts"], extra_names=names)) for t in items)
    result["style"] = _merge((t["where"], style_check.check(
        {t["where"]: t["text"]}, t["style_facts"], moment_rules=t["moment_rules"],
        extra_rules=CONNECTOR_RULES if t["connectors"] else ())) for t in items)
    result["polish"] = _merge((t["where"], polish_check.check({t["where"]: t["text"]},
                                                              sentence_fields=(t["where"],) if t["sentence"] else ()))
                              for t in items)
    result["terms"] = term_check.check(term_items(items)).to_dict()
    result["passed"] = not problems and all(result[k]["passed"] for k in ("grounding", "style", "polish", "terms"))
    return result


def flagged(checks: dict) -> list:
    """Every flagged item of run_checks() as one line of text."""
    lines = [f"format: {p}" for p in checks["format_problems"]]
    for kind in ("grounding", "style", "polish", "terms"):
        if checks[kind]:
            lines += [f'{kind}: {o["type"]} "{o["value"]}": {o["reason"]}' for o in checks[kind]["offending"]]
    return lines


# ------------------------------------------------------------ the model call

def call_model(client, deployment: str, messages: list):
    """One model call. Returns (analysis or None, problem or None, raw reply text or None)."""
    response = client.chat.completions.create(
        model=deployment,
        messages=messages,
        response_format=OUTPUT_SCHEMA,
        **MODEL_PARAMS,
    )
    choice = response.choices[0]
    content = choice.message.content
    if not content:
        return None, f"empty reply (finish_reason={choice.finish_reason})", None
    try:
        return json.loads(content), None, content
    except json.JSONDecodeError:
        return None, "reply is not valid JSON", content


def analyse(client, deployment: str, inputs: dict) -> dict:
    """Analyse the match, retrying on any failed check.

    Returns {"status": "ok" | "failed", "analysis", "checks", "retries",
    "attempts": [...]}. A failed analysis must not be used.
    """
    messages = [
        {"role": "system", "content": INSTRUCTIONS},
        {"role": "user", "content": json.dumps(inputs, ensure_ascii=False)},
    ]
    attempts = []
    for attempt in range(1 + MAX_RETRIES):
        analysis, problem, raw = call_model(client, deployment, messages)
        checks = run_checks(analysis, inputs)
        if problem:
            checks["format_problems"], checks["passed"] = [problem], False
        attempts.append({"attempt": attempt + 1, "analysis": analysis,
                         **{k: checks[k] for k in ("format_problems", "grounding", "style", "polish", "terms")}})
        if checks["passed"]:
            break

        # Tell the model exactly what failed and ask again.
        if raw is not None:
            messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": (
            "Your answer broke the rules:\n- " + "\n- ".join(flagged(checks)) +
            "\nRewrite the whole answer following every rule. Use only ids, names, numbers and minutes exactly "
            "as they appear in the input, cite every fact a phase note uses, and leave out anything you "
            "cannot support from it.")})

    last = attempts[-1]
    return {"status": "ok" if checks["passed"] else "failed", "analysis": last["analysis"],
            "checks": {k: last[k] for k in ("format_problems", "grounding", "style", "polish", "terms")},
            "retries": len(attempts) - 1, "attempts": attempts}
