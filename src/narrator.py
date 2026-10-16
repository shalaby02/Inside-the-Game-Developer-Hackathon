"""Narrator agent: turns one key moment into a short TV-analyst explanation.

The agent is defined here in code: INSTRUCTIONS (its system prompt),
OUTPUT_SCHEMA (the JSON it must return) and MODEL_PARAMS (the request
settings). It is a direct Chat Completions call to the deployed Foundry model
(same endpoint and API key as src/hello_foundry.py), not a Foundry Agent
Service agent: the Agent Service needs Entra ID sign-in (az login) and the
azure-ai-projects SDK, and this agent needs no tools or conversation history.

Every narration is checked three ways: format (JSON shape, at most 2
sentences), src/grounding.py (names, numbers, minutes) and src/style_check.py
(blocked wording). On a failure the model gets the offending items and tries
again, up to MAX_RETRIES times; after that the moment is marked failed and
its last narration is kept for inspection only.

Use:  from narrator import narrate;  narrate(client, deployment, moment)
"""

import json
import re

import grounding
import style_check

MAX_RETRIES = 2
MAX_SENTENCES = 2

# gpt-5-mini is a reasoning model. Per Microsoft's reasoning-models page it
# rejects temperature, top_p, presence/frequency penalties and max_tokens on
# Chat Completions. The output cap is max_completion_tokens, which also
# counts the model's hidden reasoning tokens, so it is set well above the
# ~150 visible tokens a narration needs.
MODEL_PARAMS = {
    "reasoning_effort": "low",
    "max_completion_tokens": 4000,
}

TEAM_NAMES = {"london_red": "London Red", "london_blue": "London Blue"}  # docs/teams.md

# Who is who in moment["players"], by category (see src/key_moments.py).
ROLES = {
    "goal": ["scorer", "key_passer"],
    "big_chance_missed": ["shooter", "key_passer"],
    "save": ["goalkeeper", "shooter", "key_passer"],
    "biggest_threat_swing": ["player", "receiver"],
}

FIELD_NOTES = """\
Field meanings (definitions only; never quote this list):
- team: the side the moment belongs to. For a save, team is the goalkeeper's side and opponent is the shooting side.
- team_score, opponent_score: the score just after the moment, from team's side.
- team_score_at_start, opponent_score_at_start (momentum_shift only): the score when the run started; goals may have come during the run, so never present it as the score during or after the run.
- action_type: "pass" or "carry", the type of the moment's key action. For a shot it is the key pass; for any other moment it is the action itself. A moment without action_type has no single key action.
- key_passer: the player who made the last pass before the shot.
- shot_x, shot_y, start_x, start_y, end_x, end_y, possession_start_x: pitch positions on a 0-100 scale; x = 100 is the goal being attacked, x below 50 is the attacking side's own half.
- shot_zone_value: xT of the spot the shot came from.
- distance_to_goal_m: distance from the shot to the goal, in metres.
- possession_seconds: how long the move took, in seconds, from its start to the shot.
- key_pass_xt_added: xT added by the key pass.
- tags "counter": the move started in the team's own half and ended in a shot within 15 seconds.
- counter_rank: 1 = the fastest counter-attack of the match; counters_in_match: how many counter-attacks the match had.
- xt_added: xT added by the action (zone_end_value minus zone_start_value).
- zone_start_value, zone_end_value: xT of the spot the ball moved from and to.
- momentum_shift: start_minute to last_minute, a run of blocks (each block_minutes long) where team created more xT than opponent; end_period is the period it ended in.
- team_threat, opponent_threat: total xT each side added during the run.
- opponent_blocks_ahead_before: how many blocks in a row opponent was on top just before the run; team_threat_before, opponent_threat_before: each side's xT over those blocks.
- top_player_threat: xT added during the run by the first of top_threat_creators."""

INSTRUCTIONS = f"""\
You are the Narrator for a football match recap: a TV analyst explaining one key moment to viewers.

xT (expected threat) is how likely a team is to score soon from where it has the ball. Every spot on the pitch has an xT value: the higher it is, the more dangerous the spot. "xT added" is how much a pass or carry raised it.

You get one moment as JSON. Write:
- headline: one short line in sentence case (capitalise only the first word and names).
- explanation: at most 2 sentences, in a confident TV-analyst voice, that explain why the moment mattered: what it did to the score, how dangerous the spot was, how fast the move was, or how much xT it added. Make one clear point and use about 4 numbers that support it. Do not list every number in the JSON.
- numbers_used: every number in your headline and explanation, exactly as written there.

Strict rules:
1. Use only the names, numbers and minutes in the moment JSON. Write player and team names exactly as given (for example "London Red").
2. Quote numbers exactly as given, digit for digit. No rounding, no conversions (no percentages, no metres to yards, no seconds to minutes), no arithmetic, no new totals, differences or ratios. Write numbers as digits, not words.
3. Say a minute as the ordinal of the minute field, such as "the 61st minute"; never "90+3". A score may be written like "1-0", using team_score and opponent_score.
4. Write durations with a hyphen and a unit: "a 7-second move", "5-minute blocks". Give distances in metres: "from 8.0 metres".
5. The only outcome verbs allowed are scored, saved, missed, passed and carried. Use passed or carried only as action_type says, and neither if there is no action_type.
6. Never describe how something looked: no volleys, headers, low shots, curling or chipped shots, shots going wide, diving, parrying or pushing-away saves, and no positions such as "central" worked out from coordinates.
7. Scores are known only at the moment itself. Never say a score stayed, held, was kept or finished that way, and never call a goal a winner or decisive.
8. Only a shot is a chance. Do not call a pass, carry or momentum shift a chance or an opportunity.
9. Do not compare the moment with the rest of the match ("the best", "the clearest so far") unless a field such as counter_rank says so.
10. Do not mention the crowd, weather, tactics, formations, managers, player history, other matches or anything else from outside the JSON. If something is not in the JSON, leave it out.
11. Do not mention ids, field names (such as shot_zone_value or xt_added) or the category label. Say "xT" for threat values.

{FIELD_NOTES}

Return only the JSON object."""

OUTPUT_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "narration",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "headline": {"type": "string"},
                "explanation": {"type": "string"},
                "numbers_used": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["headline", "explanation", "numbers_used"],
            "additionalProperties": False,
        },
    },
}


def moment_input(moment: dict) -> dict:
    """The facts object the model sees, and that the checks run against.

    Everything comes from the moment itself: team ids become their display
    names and moment["players"] gets role labels.
    """
    team = moment["team"]
    opponent = next(t for t in TEAM_NAMES if t != team)
    players = moment["players"]
    roles = ROLES.get(moment["category"])
    facts = dict(moment["facts"])
    if roles:
        people = dict(zip(roles, players))
    else:  # momentum_shift: the run's top threat creators, best first
        people = {"top_threat_creators": players}
        # Its score is the score when the run starts, not after it (goals can
        # come during the run), so the key names say so.
        for key in ("team_score", "opponent_score"):
            if key in facts:
                facts[f"{key}_at_start"] = facts.pop(key)
    return {
        "category": moment["category"],
        "tags": moment["tags"],
        "period": moment["period"],
        "minute": moment["minute"],
        "second": moment["second"],
        "team": TEAM_NAMES[team],
        "opponent": TEAM_NAMES[opponent],
        **people,
        "facts": facts,
    }


def sentence_count(text: str) -> int:
    # A sentence ends at . ! or ? followed by a space or the end ("0.3" is not an end).
    return len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s])


def format_problems(narration) -> list:
    if not isinstance(narration, dict):
        return ["response is not a JSON object"]
    problems = []
    for key in ("headline", "explanation"):
        if not isinstance(narration.get(key), str) or not narration[key].strip():
            problems.append(f"{key} is missing or empty")
    if not isinstance(narration.get("numbers_used"), list):
        problems.append("numbers_used is not a list")
    if not problems:
        n = sentence_count(narration["explanation"])
        if n > MAX_SENTENCES:
            problems.append(f"explanation has {n} sentences, at most {MAX_SENTENCES} allowed")
    return problems


def call_model(client, deployment: str, messages: list):
    """One model call. Returns (narration or None, problem or None, raw reply text or None)."""
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


def narrate(client, deployment: str, moment: dict) -> dict:
    """Narrate one moment, retrying on a format, grounding or style failure.

    Returns {"id", "status": "ok" | "failed", "narration", "grounding",
    "style", "retries", "attempts": [...]}. A failed moment's narration must
    not be used.
    """
    facts = moment_input(moment)
    messages = [
        {"role": "system", "content": INSTRUCTIONS},
        {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
    ]
    attempts = []
    for attempt in range(1 + MAX_RETRIES):
        narration, problem, raw = call_model(client, deployment, messages)
        problems = [problem] if problem else format_problems(narration)
        ground = grounding.check(narration, facts).to_dict() if narration is not None else None
        style = style_check.check(narration, facts).to_dict() if narration is not None else None
        attempts.append({"attempt": attempt + 1, "narration": narration, "format_problems": problems,
                         "grounding": ground, "style": style})
        if not problems and ground["passed"] and style["passed"]:
            break

        # Tell the model exactly what failed and ask again.
        feedback = list(problems)
        for result in (ground, style):
            if result:
                feedback += [f'{o["type"]} "{o["value"]}": {o["reason"]}' for o in result["offending"]]
        if raw is not None:
            messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": (
            "Your answer broke the rules:\n- " + "\n- ".join(feedback) +
            "\nRewrite it following every rule. Use only names, numbers and minutes exactly as they appear "
            "in the moment JSON, and leave out anything you cannot support from it.")})

    last = attempts[-1]
    ok = not last["format_problems"] and last["grounding"]["passed"] and last["style"]["passed"]
    return {"id": moment["id"], "status": "ok" if ok else "failed", "narration": last["narration"],
            "grounding": last["grounding"], "style": last["style"], "retries": len(attempts) - 1,
            "attempts": attempts}
