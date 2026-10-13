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

xT note for Day 4: only `pass` and `carry` with outcome `complete` get an "xT added" value (value at end − value at start). The other types are kept for context: turnovers, pressure and fouls.
