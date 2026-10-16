# Match data format

This is the shape of `data/match.json`, the file that `src/generate_match.py` will write (Day 3) and that `src/xt_model.py` will read (Day 4).

## The pitch

- Both axes run from **0 to 100**. This is the same as Opta's layout, so mplsoccer can draw it with `Pitch(pitch_type="opta")`.
- **Every event is stored from the acting team's point of view, and that team always attacks toward x = 100.** London Red and London Blue both shoot at x = 100 in their own events.
- `x = 0` is the team's own goal line and `x = 100` is the goal line they attack.
- `y = 0` is the touchline on the attacker's **right**, and `y = 100` is the one on their **left**. The goal is centred on `y = 50`.
- The goal mouth is roughly `y = 45` to `y = 55` at `x = 100`. The penalty box is roughly `x ≥ 83`, `21 ≤ y ≤ 79`.

```
 y=100 ┌───────────────────────────────────────────┐  (attacker's left)
       │                                           │
       │                                     ┌─────┤
       │                                     │  box│
 y=50  │ own goal                            │     ║ goal they attack
       │ x=0                                 │     │ x=100
       │                                     └─────┤
       │                                           │
 y=0   └───────────────────────────────────────────┘  (attacker's right)
        ─────────────── direction of attack ──────▶
```

To draw both teams on one pitch (for example, Red attacking left to right and Blue attacking right to left), flip the other team's events: `x' = 100 − x`, `y' = 100 − y`.

## Event fields

| Field | Type | Meaning |
|---|---|---|
| `event_id` | int | Running number, starts at 1, goes up by 1 in match order. |
| `possession_id` | int | Groups the events of one attacking move. A new id starts each time the ball changes team, and at every restart (kick-off, set piece). |
| `period` | int | `1` = first half, `2` = second half. |
| `minute` | int | Match clock minute. The first half runs from `0`, and the second half starts at `45`. Stoppage time keeps counting, so first-half 45+2 is `period: 1, minute: 47`, which is different from `period: 2, minute: 47`. |
| `second` | int | `0`–`59`. |
| `team` | string | `london_red` or `london_blue`. The team of the player who made the event. |
| `player` | string | The player's full name, exactly as written in [teams.md](teams.md). |
| `shirt_number` | int | The player's shirt number from [teams.md](teams.md). Together with `team`, this is the reliable way to identify a player. Use the name for display only. |
| `type` | string | One of `pass`, `carry`, `shot`, `tackle`, `interception`, `foul`, `clearance`. |
| `start_x`, `start_y` | number | Where the event started, 0–100, from the acting team's point of view. |
| `end_x`, `end_y` | number | Where the ball ended up. For `tackle`, `interception` and `foul` this is the same as the start. |
| `outcome` | string | Depends on `type`. See the next table. |
| `is_assist` | bool | `true` only on the pass that set up a goal. `false` everywhere else. |

Numbers may have one decimal place (for example `57.5`).

## Allowed outcomes for each type

| Type | Allowed `outcome` values | Notes |
|---|---|---|
| `pass` | `complete`, `incomplete` | `incomplete` = intercepted, or out of play. Only a `complete` pass can have `is_assist: true`. |
| `carry` | `complete`, `lost` | Player runs with the ball. `lost` = dispossessed during the carry. |
| `shot` | `goal`, `saved`, `off_target`, `blocked` | For `goal` and `off_target`, the end point is where the ball crossed the goal line (`end_x = 100`). For `saved` and `blocked`, it is where the ball was stopped. Saves have no event of their own: a `saved` shot is credited to the other team's goalkeeper. |
| `tackle` | `won`, `lost` | `won` = the tackler's team now has the ball. A won tackle starts a new possession for the tackler's team. |
| `interception` | `won` | Always wins the ball. Starts a new possession for the intercepting team. |
| `foul` | `free_kick`, `yellow_card`, `red_card` | Recorded for the team that **committed** the foul, at the spot of the foul, from that team's point of view. |
| `clearance` | `won`, `lost` | `won` = the clearing team, or nobody, has the ball next. `lost` = the opponent picks it up. |

## Rules the generator must follow

1. Events are in time order (`period`, then `minute`, then `second`), and `event_id` follows that order.
2. A goal always comes straight after its assist pass, if there was one, and both are in the same `possession_id`. Some goals have no assist (a solo run, a rebound).
3. A pass's end point is the next event's start point when the same team keeps the ball.
4. The number of `shot` events with `outcome: goal` for each team must match the final score in [match-story.md](match-story.md).
5. Every `player` and `shirt_number` pair must match the right `team` in [teams.md](teams.md).
6. Set pieces (corners, free kicks, kick-offs, goal kicks) have no event type of their own. They just start a new `possession_id`.

## File shape

```json
{
  "match": {
    "home_team": "london_red",
    "away_team": "london_blue",
    "final_score": { "london_red": 2, "london_blue": 1 },
    "seed": 42
  },
  "events": [ { "event_id": 1, "...": "..." } ]
}
```

## Example: one attacking move in 5 events

London Blue's goal (second half, 61'), a turnover in midfield followed by a quick break down the left.

| # | Time | Player (No.) | Type | From → To | Outcome |
|---|---|---|---|---|---|
| 1 | 61:04 | Sam Okoro (4) | tackle | (44, 46) | won |
| 2 | 61:07 | Sam Okoro (4) | pass | (44, 46) → (58, 70) | complete |
| 3 | 61:10 | Dario Quill (11) | carry | (58, 70) → (74, 76) | complete |
| 4 | 61:13 | Dario Quill (11) | pass | (74, 76) → (88, 52) | complete, `is_assist` |
| 5 | 61:14 | Niko Vane (9) | shot | (88, 52) → (100, 50) | goal |

In words: Okoro wins the ball just short of halfway, Quill runs with it up the left wing, crosses into the box, and Vane scores in the middle of the goal.

The same move as JSON (the event and possession ids are examples):

```json
[
  { "event_id": 312, "possession_id": 141, "period": 2, "minute": 61, "second": 4,  "team": "london_blue", "player": "Sam Okoro",   "shirt_number": 4,  "type": "tackle", "start_x": 44, "start_y": 46, "end_x": 44,  "end_y": 46, "outcome": "won",      "is_assist": false },
  { "event_id": 313, "possession_id": 141, "period": 2, "minute": 61, "second": 7,  "team": "london_blue", "player": "Sam Okoro",   "shirt_number": 4,  "type": "pass",   "start_x": 44, "start_y": 46, "end_x": 58,  "end_y": 70, "outcome": "complete", "is_assist": false },
  { "event_id": 314, "possession_id": 141, "period": 2, "minute": 61, "second": 10, "team": "london_blue", "player": "Dario Quill", "shirt_number": 11, "type": "carry",  "start_x": 58, "start_y": 70, "end_x": 74,  "end_y": 76, "outcome": "complete", "is_assist": false },
  { "event_id": 315, "possession_id": 141, "period": 2, "minute": 61, "second": 13, "team": "london_blue", "player": "Dario Quill", "shirt_number": 11, "type": "pass",   "start_x": 74, "start_y": 76, "end_x": 88,  "end_y": 52, "outcome": "complete", "is_assist": true  },
  { "event_id": 316, "possession_id": 141, "period": 2, "minute": 61, "second": 14, "team": "london_blue", "player": "Niko Vane",   "shirt_number": 9,  "type": "shot",   "start_x": 88, "start_y": 52, "end_x": 100, "end_y": 50, "outcome": "goal",     "is_assist": false }
]
```

## Expected Threat (xT)

`src/xt_model.py` reads `data/match.json` and writes `data/match_xt.csv`: the same columns, plus these:

| Column | Type | Meaning |
|---|---|---|
| `zone_start`, `zone_end` | string | Zone of the start and end point, e.g. `c10r4` (see below). |
| `xt_added` | number | How much the event changed its team's chance of scoring soon (see the table below). |
| `shot_zone_value` | number or blank | Shots only: the value of the zone the shot was taken from, a measure of how good the chance was. Blank for other types. |
| `possession_seconds` | int | The same on every event of a possession: seconds from its first event to its shot, or to its last event if there was no shot. Use it for tempo, e.g. the fastest moves from a team's own half (`start_x` < 50 on the first event) to a shot. |

**Zones.** The pitch is split into 12 columns along `x` (each 8.33 wide) and 8 rows along `y` (each 12.5 wide), in the acting team's frame. A zone is written `c{column}r{row}`: `c0` is at the team's own goal line, `c11` is next to the goal they attack, and `r0` is the attacker's right touchline. Points on `x = 100` or `y = 100` fall in the last zone. For example, `(88, 52)` is in `c10r4`.

**Zone values.** Each zone's value is roughly "how likely is a goal soon if we have the ball here". The values are hand-built, with no outside data: the value halves for every 8 units the zone's centre is from the middle of the goal (100, 50). Sideways distance counts 70%, so the wide zones by the byline still have some value. The best zone is scaled to 0.30. The values go from about 0.005 in the centre circle to 0.08 at the edge of the box and 0.30 in front of goal.

**xT added per event.**

| Event | `xt_added` |
|---|---|
| `pass` / `carry`, `complete` | value(end zone) − value(start zone) |
| `pass` `incomplete`, `carry` `lost` | − value(start zone): the team gave away what it had |
| `shot` | 0: its danger is in `shot_zone_value` instead, so goals don't swamp the totals |
| `tackle`, `interception`, `foul`, `clearance` | 0 (kept for context) |

Example: Quill's assist at 61' goes from `c8r6` (0.021) to `c10r4` (0.161), so `xt_added` = +0.139. Vane's goal straight after has `xt_added` = 0 and `shot_zone_value` = 0.161.

## Key moments

`src/key_moments.py` reads `data/match_xt.csv` and writes `data/key_moments.json`: the final score and about 10–12 moments in match order. Moments are facts only, with no prose, so the Narrator can explain them without inventing anything.

```json
{
  "final_score": { "london_red": 2, "london_blue": 1 },
  "moments": [
    { "id": "m10", "category": "goal", "tags": ["counter"], "period": 2, "minute": 74, "second": 22,
      "team": "london_red", "players": ["Rafael Tovey", "Theo Brannick"],
      "facts": { "action_type": "pass", "build_up": "London Red won the ball back in the defensive third and scored 12 seconds later, ...", "score_effect": "levelled the match at 1-1", "possession_seconds": 12, "possession_start_x": 17.0, "counter_rank": 2, "team_score": 1, "opponent_score": 1, "...": "..." } }
  ]
}
```

| Field | Meaning |
|---|---|
| `id` | `m01`, `m02`, … in match order. |
| `category` | One per moment (see the next table). |
| `tags` | A list, often empty. `counter` = the moment's possession starts in the team's own half (`start_x` < 50 on its first event), ends in a shot and takes 15 seconds or less. |
| `period`, `minute`, `second` | When it happened. A momentum shift is timed at the start of its first block. |
| `team` | The team the moment belongs to. For a `save`, that's the goalkeeper's team. |
| `players` | Names, most important first: scorer then assist, goalkeeper then shooter, passer then receiver, or a momentum shift's top 3 threat creators. |
| `facts` | Plain numbers, e.g. `xt_added`, `shot_zone_value`, `possession_seconds`, plus the code-derived words below (`action_type`, `score_effect`, `build_up`, `counter_label`). `team_score` and `opponent_score` are the score just after the moment (for a momentum shift: when its first block starts). |
| `facts.score_effect` | Goals only. What the goal did to the score, from the scoring team's side: `put London Blue 1-0 up` (first goal), `put London Red 2-1 ahead` (from level), `levelled the match at 1-1`, `extended <team>'s lead to 2-0`, `pulled <team> back to 1-2`. |
| `facts.build_up` | Shot moments and threat swings, when the events support it. One complete sentence that names the attacking team (for a save: the shooting team), e.g. `London Blue won the ball back in midfield and scored 10 seconds later, after 2 passes and a carry from midfield into the attacking third.` It says how the possession reached the key action (the shot, or the swing's pass or carry: `played this pass`, `made this carry`, with the passes before it called `earlier`), built only from what the events record: **start** `<team> won the ball back in <third>` when the possession's first event is the team's own won `tackle` or `interception`, or `<team>'s move started after a <other team> foul` when the event just before the possession is the other team's foul; **middle** the number of completed passes, a forward carry of at least 10 pitch units (described by thirds: the defensive third, midfield, the attacking third), and `a one-two` (A passes, B passes, A is next on the ball). A duration (`and scored 10 seconds later`) appears only after a won ball, the only start with a recorded time. Not derivable, so never included: throw-ins, corners, goal kicks and other restarts (they have no events), and pass length or style. Momentum shifts have none. |
| `facts.counter_label` | Goals with the `counter` tag only: `the fastest of the match's two counter-attacks`, `the second-fastest of the match's two counter-attacks`. |
| `facts.action_type` | `pass` or `carry`: the type of the moment's key action. For a `biggest_threat_swing` that is the swing itself; for a shot moment it is the key pass (the last pass before the shot, so always `pass`, and present only when `key_pass_xt_added` is). Momentum shifts have no key action and no `action_type`. |

| Category | Rule |
|---|---|
| `goal` | Every goal, always included. A goal with the `counter` tag also has `counter_rank` (1 = the fastest `counter` move in the match, by `possession_seconds`) and `counters_in_match` (how many moves meet the `counter` rule). |
| `save` | A saved shot from a big chance (`shot_zone_value` ≥ 0.15). |
| `big_chance_missed` | An off-target or blocked shot from a big chance. |
| `momentum_shift` | One team creates more threat than the other in at least 3 five-minute blocks in a row, after the other team was on top in the block before, and beats the other team's threat over those blocks by at least 0.25. Threat = `xt_added` of completed passes and carries only. |
| `biggest_threat_swing` | The completed passes and carries with the most `xt_added`. |

**Selection.** Goals first. Then the other categories in the order of the table, best first, with at most 3 moments per category and at most one moment per 60 seconds.
