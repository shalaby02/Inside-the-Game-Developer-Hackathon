"""Narrator agent: turns one key moment into a short TV-analyst explanation.

The agent is defined here in code: INSTRUCTIONS (its system prompt),
OUTPUT_SCHEMA (the JSON it must return) and MODEL_PARAMS (the request
settings). It is a direct Chat Completions call to the deployed Foundry model
(same endpoint and API key as src/hello_foundry.py), not a Foundry Agent
Service agent: the Agent Service needs Entra ID sign-in (az login) and the
azure-ai-projects SDK, and this agent needs no tools or conversation history.

Every narration is checked by src/grounding.py. On a failure the model gets
the offending items and tries again, up to MAX_RETRIES times; after that the
moment is marked failed and its last narration is kept for inspection only.

Use:  from narrator import narrate;  narrate(client, deployment, moment)
"""

import json
import re

from grounding import check

MAX_RETRIES = 2

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
    "biggest_threat_swing": ["passer_or_carrier", "receiver"],
}

FIELD_NOTES = """\
Field meanings (definitions only; never quote this list):
- team: the side the moment belongs to. For a save, team is the goalkeeper's side and opponent is the shooting side.
- team_score, opponent_score: the score just after the moment, from team's side.
- team_score_at_start, opponent_score_at_start (momentum_shift only): the score when the run started; goals may have come during the run, so never present it as the score during or after the run.
- key_passer: the player who made the last pass before the shot.
- shot_x, shot_y, start_x, start_y, end_x, end_y, possession_start_x: pitch positions on a 0-100 scale; x = 100 is the goal being attacked, x below 50 is the attacking side's own half.
- shot_zone_value: expected threat (xT) of the zone the shot came from; higher means a more dangerous position.
- distance_to_goal_m: distance from the shot to the goal, in metres.
- possession_seconds: how long the move took, in seconds, from its start to the shot.
- key_pass_xt_added: xT added by the key pass.
- tags "counter": the move started in the team's own half and ended in a shot within 15 seconds.
- counter_rank: 1 = the fastest counter-attack of the match; counters_in_match: how many counter-attacks the match had.
- xt_added: how much the pass or carry raised the team's threat (zone_end_value minus zone_start_value).
- zone_start_value, zone_end_value: xT of the zone the ball moved from and to.
- momentum_shift: start_minute to last_minute, a run of blocks (each block_minutes long) where team created more threat than opponent; end_period is the period it ended in.
- team_threat, opponent_threat: total xT each side created during the run.
- opponent_blocks_ahead_before: how many blocks in a row opponent was on top just before the run; team_threat_before, opponent_threat_before: each side's xT over those blocks.
- top_player_threat: xT created during the run by the first of top_threat_creators."""

INSTRUCTIONS = f"""\
You are the Narrator for a football match recap: a TV analyst explaining one key moment to viewers.

You get one moment as JSON. Write:
- headline: one short line, in sentence case (capitalise only the first word and names).
- explanation: 2 or 3 sentences in a confident TV-analyst voice that explain why the moment mattered, using what the facts show (the score it left, how dangerous the position was, how fast the move was, how much threat it created).
- numbers_used: every number that appears in your headline and explanation, written exactly as it appears there.

Strict rules:
1. Use only the names, numbers and minutes in the moment JSON. Write player names exactly as given, and team names exactly as given (for example "London Red").
2. Quote numbers exactly as given, digit for digit. No rounding, no conversions (no percentages, no metres to yards, no seconds to minutes), no arithmetic, no new totals, no differences or ratios. Write numbers as digits, not words.
3. Say a minute as the ordinal of the minute field, such as "the 61st minute". Never give a stoppage-time form like "90+3". A score may be written like "1-0", using team_score and opponent_score.
4. Do not mention the crowd, weather, tactics, formations, managers, player history, other matches or anything else from outside the JSON.
5. If something is not in the JSON, leave it out. Do not guess. That includes how an action looked: no volleys, headers, low shots, diving or smothering saves, shots going wide, curling or diagonal balls, and no saying whether a move was a pass or a carry unless the JSON says so.
6. Do not mention ids, field names (such as shot_zone_value or xt_added) or the category label. Say "xT" for threat values.
7. Give a unit with every number that has one: metres for distance_to_goal_m, seconds for possession_seconds, minutes for block_minutes. Leave out raw pitch positions unless they explain why the moment mattered.
8. Scores are only known at the moment itself. Never say a score stayed the same, held or finished that way, and do not call a goal a winner.
9. Only a shot is a chance. Do not call a pass, carry or momentum shift a chance.
10. Do not compare the moment with the rest of the match ("the best of the game", "the clearest so far") unless a field such as counter_rank says so.

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
    """The facts object the model sees, and that grounding checks against.

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
        if not 2 <= n <= 3:
            problems.append(f"explanation has {n} sentences, needs 2 or 3")
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
    """Narrate one moment, retrying on a grounding or format failure.

    Returns {"id", "status": "ok" | "failed", "narration", "grounding",
    "attempts": [...]}. A failed moment's narration must not be used.
    """
    facts = moment_input(moment)
    messages = [
        {"role": "system", "content": INSTRUCTIONS},
        {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
    ]
    attempts = []
    narration, grounding = None, None
    for attempt in range(1 + MAX_RETRIES):
        narration, problem, raw = call_model(client, deployment, messages)
        problems = [problem] if problem else format_problems(narration)
        grounding = check(narration, facts).to_dict() if narration is not None else None
        attempts.append({"attempt": attempt + 1, "narration": narration,
                         "format_problems": problems, "grounding": grounding})
        if not problems and grounding["passed"]:
            return {"id": moment["id"], "status": "ok", "narration": narration,
                    "grounding": grounding, "attempts": attempts}

        # Tell the model exactly what failed and ask again.
        feedback = list(problems)
        if grounding:
            feedback += [f'{o["type"]} "{o["value"]}": {o["reason"]}' for o in grounding["offending"]]
        if raw is not None:
            messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": (
            "Your answer broke the rules:\n- " + "\n- ".join(feedback) +
            "\nRewrite it using only names, numbers and minutes exactly as they appear in the moment JSON. "
            "Leave out anything you cannot support from it.")})

    return {"id": moment["id"], "status": "failed", "narration": narration,
            "grounding": grounding, "attempts": attempts}
