"""Generate the synthetic match: data/match.json and data/match.csv.

Follows docs/data-format.md (event shape and rules), docs/teams.md (players)
and docs/match-story.md (score and planted story moments).

How it works:
- The match clock is split into segments of random "filler" play, with the
  six planted story moments written in by hand between them.
- Filler play is a simple possession simulator: the player on the ball
  passes, carries, shoots or clears; the other team tackles, intercepts and
  fouls. How well each team plays changes by phase of the match (see PHASES),
  which is what gives the xT-over-time story its shape.
- A fixed random seed makes the match identical on every run.

Run:  python src/generate_match.py
"""

import csv
import json
import math
import random
from pathlib import Path

SEED = 42
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

RED, BLUE = "london_red", "london_blue"
FINAL_SCORE = {RED: 2, BLUE: 1}

FIELDS = [
    "event_id", "possession_id", "period", "minute", "second", "team", "player",
    "shirt_number", "type", "start_x", "start_y", "end_x", "end_y", "outcome",
    "is_assist",
]

# shirt -> (name, base x, base y). Base spots are in the team's own frame
# (attacking toward x = 100, y = 0 on the attacker's right) with the ball
# around halfway. Outfield players shift up and down the pitch with the ball.
SQUADS = {
    RED: {  # 4-4-2
        1: ("Ellis Harwick", 5, 50),
        2: ("Jonah Pellow", 28, 12),
        5: ("Rory Calloway", 20, 38),
        4: ("Ade Fenwright", 20, 62),
        3: ("Kofi Ashdown", 28, 88),
        7: ("Theo Brannick", 55, 12),
        8: ("Luca Merriden", 46, 40),
        6: ("Idris Stanbury", 44, 60),
        11: ("Femi Oakhurst", 55, 88),
        10: ("Rafael Tovey", 72, 42),
        9: ("Cass Dunmore", 72, 58),
    },
    BLUE: {  # 4-3-3
        1: ("Bram Hollis", 5, 50),
        2: ("Yusuf Calder", 30, 12),
        5: ("Owen Strand", 20, 38),
        6: ("Matteo Lisk", 20, 62),
        3: ("Jamal Prewitt", 30, 88),
        4: ("Sam Okoro", 36, 50),
        8: ("Felix Ardent", 50, 35),
        10: ("Kai Renwick", 50, 65),
        7: ("Tobi Wexley", 70, 14),
        11: ("Dario Quill", 70, 86),
        9: ("Niko Vane", 78, 50),
    },
}

KICKOFF = {RED: (10, 8), BLUE: (9, 4)}  # (taker, receiver)

# How likely each player is to carry the ball instead of passing.
CARRY_PROB = {
    RED: {1: 0.0, 2: 0.3, 5: 0.1, 4: 0.1, 3: 0.3, 7: 0.45, 8: 0.25, 6: 0.25,
          11: 0.45, 10: 0.35, 9: 0.3},
    BLUE: {1: 0.0, 2: 0.3, 5: 0.1, 6: 0.1, 3: 0.3, 4: 0.2, 8: 0.25, 10: 0.25,
           7: 0.45, 11: 0.45, 9: 0.3},
}

# Team behaviour by phase. Keys:
#   comp      base pass completion
#   fwd       preference for forward passes (negative = plays backwards)
#   shoot     chance of shooting when on the ball in the box
#   deep      below this x, the player on the ball may just clear it
#   hoof      chance of clearing when on the ball below `deep`
#   clear_won chance that a clearance is "won"
#   foul      chance of fouling the opponent's ball carrier, per action
PHASES = [
    # (period, from minute, to minute, red params, blue params)
    (1, 0, 99,
     dict(comp=0.88, fwd=1.0, shoot=0.30, deep=30, hoof=0.10, clear_won=0.6, foul=0.040),
     dict(comp=0.76, fwd=0.35, shoot=0.40, deep=30, hoof=0.35, clear_won=0.5, foul=0.060)),
    (2, 45, 60,  # even after the break
     dict(comp=0.84, fwd=0.7, shoot=0.30, deep=30, hoof=0.20, clear_won=0.6, foul=0.045),
     dict(comp=0.82, fwd=0.7, shoot=0.35, deep=30, hoof=0.25, clear_won=0.6, foul=0.045)),
    (2, 60, 70,  # Blue on top: goal at 61', big chance at 67'
     dict(comp=0.74, fwd=0.2, shoot=0.25, deep=30, hoof=0.45, clear_won=0.5, foul=0.060),
     dict(comp=0.88, fwd=1.1, shoot=0.35, deep=30, hoof=0.10, clear_won=0.6, foul=0.040)),
    (2, 70, 80,  # Red take over after the save
     dict(comp=0.88, fwd=1.2, shoot=0.30, deep=30, hoof=0.05, clear_won=0.6, foul=0.040),
     dict(comp=0.66, fwd=-0.2, shoot=0.25, deep=40, hoof=0.75, clear_won=0.45, foul=0.060)),
    (2, 80, 99,  # Blue camp in their own box and clear everything
     dict(comp=0.90, fwd=1.3, shoot=0.30, deep=30, hoof=0.05, clear_won=0.6, foul=0.040),
     dict(comp=0.55, fwd=-0.5, shoot=0.25, deep=60, hoof=0.95, clear_won=0.30, foul=0.020)),
]


def other(team):
    return BLUE if team == RED else RED


def clamp(v, lo=0, hi=100):
    return max(lo, min(hi, v))


def flip(x, y):
    """Convert a point to the other team's frame."""
    return 100 - x, 100 - y


def reach(x, y, start_x):
    """Limit where a filler pass or carry can end. Filler play stops at the
    edge of the box in the middle (it can go deeper out wide), and one
    possession moves the ball at most
    60 units up the pitch. This keeps the planted moments as the biggest
    xT gains (moment 5 must be the biggest single possession)."""
    cap = 83 if 30 < y < 70 else 95
    return min(x, cap, start_x + 60)


def clock(mmss):
    """'61:04' -> seconds on the match clock."""
    m, s = mmss.split(":")
    return int(m) * 60 + int(s)


class MatchGenerator:
    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.events = []
        self.possession_id = 0
        self.booked = set()

    # ------------------------------------------------------------------ basics

    def add(self, period, t, team, shirt, type_, start, end=None, outcome="",
            is_assist=False, new_possession=False):
        if new_possession:
            self.possession_id += 1
        end = end if end is not None else start
        sx, sy = (round(clamp(v), 1) for v in start)
        ex, ey = (round(clamp(v), 1) for v in end)
        self.events.append({
            "possession_id": self.possession_id,
            "period": period,
            "minute": t // 60,
            "second": t % 60,
            "team": team,
            "player": SQUADS[team][shirt][0],
            "shirt_number": shirt,
            "type": type_,
            "start_x": sx, "start_y": sy, "end_x": ex, "end_y": ey,
            "outcome": outcome,
            "is_assist": is_assist,
        })

    def params(self, team, period, t):
        minute = t // 60
        for p, lo, hi, red, blue in PHASES:
            if p == period and lo <= minute < hi:
                return red if team == RED else blue
        raise ValueError(f"no phase for period {period} minute {minute}")

    def spot(self, team, shirt, ball_x):
        """Where a player stands when their team has the ball at ball_x."""
        _, bx, by = SQUADS[team][shirt]
        if shirt == 1:
            return bx, by
        # The team pushes up with the ball, and drops back (more compactly)
        # when the ball is deep, but never onto its own goal line.
        k = 0.5 if ball_x > 50 else 0.35
        return clamp(bx + (ball_x - 50) * k, 10, 96), by

    def nearest(self, team, x, y, exclude=()):
        """Outfield player of `team` closest to (x, y), in that team's frame."""
        best = None
        for shirt in SQUADS[team]:
            if shirt == 1 or shirt in exclude:
                continue
            px, py = self.spot(team, shirt, x)
            d = math.hypot(px - x, py - y)
            if best is None or d < best[0]:
                best = (d, shirt)
        return best[1]

    def pick_receiver(self, team, holder, x, y, fwd):
        shirts, weights = [], []
        for shirt in SQUADS[team]:
            if shirt == holder:
                continue
            rx, ry = self.spot(team, shirt, x)
            d = math.hypot(rx - x, ry - y)
            w = math.exp(-d / 22) * math.exp(clamp(fwd * (rx - x) / 25, -5, 5))
            if shirt == 1:
                w *= 0.3 if x < 35 else 0.0
            shirts.append(shirt)
            weights.append(w)
        shirt = self.rng.choices(shirts, weights)[0]
        rx, ry = self.spot(team, shirt, x)
        tx = clamp(rx + self.rng.gauss(0, 5), 5, 99)
        ty = clamp(ry + self.rng.gauss(0, 8), 1, 99)
        return shirt, tx, ty

    # ------------------------------------------------------------ filler play

    def play(self, period, t, t_end, team, kind, x, y):
        """Random play from t until just before t_end."""
        while True:
            nxt = self.possession(period, t, t_end, team, kind, x, y)
            if nxt is None:
                return
            t, team, kind, x, y = nxt

    def possession(self, period, t, t_end, team, kind, x, y):
        """Play one possession. Returns how the next one starts, or None if
        time ran out. `kind` says how this team got the ball."""
        rng = self.rng
        if t >= t_end:
            return None
        p = self.params(team, period, t)
        q = self.params(other(team), period, t)
        opp = other(team)
        self.possession_id += 1

        force = None
        if kind == "kickoff":
            holder, x, y = KICKOFF[team][0], 50, 50
            force = "kickoff"
        elif kind in ("goal_kick", "keeper"):
            holder = 1
            if kind == "goal_kick":
                x, y = 6, 50
            # A team under siege just boots it long.
            force = "clearance" if p["hoof"] >= 0.9 else "pass"
        elif kind == "throw_in":
            y = 0 if y < 50 else 100
            holder = self.nearest(team, x, y)
            force = "pass"
        elif kind == "corner":
            x, y = 99.5, (0.5 if y < 50 else 99.5)
            holder = self.nearest(team, 90, y)
            force = "corner"
        elif kind == "free_kick":
            holder = self.nearest(team, x, y)
            force = "pass"
        elif kind == "pickup":
            holder = self.nearest(team, x, y)
        elif kind in ("interception", "tackle"):
            holder = self.nearest(team, x, y)
            if x < p["deep"] and rng.random() < p["hoof"]:
                force = "clearance"  # under pressure: just get rid of it
            else:
                self.add(period, t, team, holder, kind, (x, y), outcome="won")
                t += 1
        else:
            raise ValueError(kind)

        start_x = x
        n = 0
        while True:
            n += 1
            if t >= t_end:
                return None
            action = force
            force = None

            # The defending team may foul the player on the ball (never in
            # the box: the story has no penalties).
            if action is None and 15 < x < 80 and rng.random() < q["foul"]:
                fx, fy = flip(x, y)
                fouler = self.nearest(opp, fx, fy)
                outcome = "free_kick"
                if (opp, fouler) not in self.booked and rng.random() < 0.15:
                    outcome = "yellow_card"
                    self.booked.add((opp, fouler))
                self.add(period, t, opp, fouler, "foul", (fx, fy), outcome=outcome)
                return t + rng.randint(20, 40), team, "free_kick", x, y

            if action is None:
                in_box = x >= 83 and 21 <= y <= 79
                edge = 75 <= x < 83 and 30 <= y <= 70
                if x < p["deep"] and rng.random() < p["hoof"]:
                    action = "clearance"
                elif in_box and rng.random() < p["shoot"]:
                    action = "shot"
                elif edge and rng.random() < 0.10:
                    action = "shot"
                elif rng.random() < CARRY_PROB[team][holder]:
                    action = "carry"
                else:
                    action = "pass"

            if action in ("pass", "kickoff", "corner"):
                if action == "kickoff":
                    r = KICKOFF[team][1]
                    tx, ty, pc = 40, 50 + rng.gauss(0, 4), 1.0
                elif action == "corner":
                    tx, ty = 90 + rng.uniform(-4, 4), 50 + rng.gauss(0, 7)
                    r = self.nearest(team, tx, ty)
                    pc = 0.35
                else:
                    r, tx, ty = self.pick_receiver(team, holder, x, y, p["fwd"])
                    dist = math.hypot(tx - x, ty - y)
                    pc = p["comp"] - 0.005 * max(0, dist - 20) - 0.02 * max(0, n - 8)
                    if tx > 83:
                        pc -= 0.10
                    pc = clamp(pc, 0.25, 0.95)
                tx = reach(tx, ty, start_x)
                dist = math.hypot(tx - x, ty - y)
                dt = round(3 + dist / 9 + rng.uniform(0, 3.5))
                if rng.random() < pc:
                    self.add(period, t, team, holder, "pass", (x, y), (tx, ty), "complete")
                    t += dt
                    holder, x, y = r, tx, ty
                    continue
                # Incomplete: out of play, or picked off by the other team.
                if (ty < 15 or ty > 85) and rng.random() < 0.5:
                    ty = 0 if ty < 50 else 100
                    self.add(period, t, team, holder, "pass", (x, y), (tx, ty), "incomplete")
                    return t + dt + rng.randint(15, 25), opp, "throw_in", *flip(tx, ty)
                self.add(period, t, team, holder, "pass", (x, y), (tx, ty), "incomplete")
                return t + dt + rng.randint(1, 3), opp, "interception", *flip(tx, ty)

            if action == "carry":
                _, _, by = SQUADS[team][holder]
                ex = clamp(x + clamp(rng.gauss(6 + 3 * p["fwd"], 4), -3, 18), 1, 97)
                ey = clamp(y + rng.gauss((by - y) * 0.25, 5), 1, 99)
                ex = max(x, reach(ex, ey, start_x)) if ex > x else ex
                dt = round(2 + math.hypot(ex - x, ey - y) / 3 + rng.uniform(0, 1.5))
                lost = rng.random() < 0.10 + (0.08 if x > 65 else 0)
                if lost:
                    self.add(period, t, team, holder, "carry", (x, y), (ex, ey), "lost")
                    return t + dt, opp, "tackle", *flip(ex, ey)
                self.add(period, t, team, holder, "carry", (x, y), (ex, ey), "complete")
                t += dt
                x, y = ex, ey
                if t < t_end and rng.random() < 0.12:  # a defender dives in and misses
                    fx, fy = flip(x, y)
                    self.add(period, t, opp, self.nearest(opp, fx, fy), "tackle",
                             (fx, fy), outcome="lost")
                    t += 1
                continue

            if action == "clearance":
                ex = clamp(x + rng.uniform(25, 45), 1, 99)
                ey = clamp(y + rng.gauss(0, 18), 1, 99)
                dt = round(2 + rng.uniform(0, 2))
                won = rng.random() < p["clear_won"]
                if won and rng.random() < 0.5:  # a team-mate collects it
                    self.add(period, t, team, holder, "clearance", (x, y), (ex, ey), "won")
                    t += dt
                    holder, x, y = self.nearest(team, ex, ey), ex, ey
                    continue
                if won:  # out of play
                    ey = 0 if ey < 50 else 100
                    self.add(period, t, team, holder, "clearance", (x, y), (ex, ey), "won")
                    return t + dt + rng.randint(15, 25), opp, "throw_in", *flip(ex, ey)
                self.add(period, t, team, holder, "clearance", (x, y), (ex, ey), "lost")
                return t + dt, opp, "pickup", *flip(ex, ey)

            if action == "shot":
                outcome = rng.choices(["saved", "off_target", "blocked"], [35, 40, 25])[0]
                if outcome == "off_target":
                    side = rng.choice([-1, 1])
                    ex, ey = 100, 50 + side * rng.uniform(6, 20)
                elif outcome == "saved":
                    ex, ey = rng.uniform(97, 99.5), rng.uniform(44, 56)
                else:
                    ex, ey = min(99, x + rng.uniform(2, 6)), y + rng.gauss(0, 4)
                self.add(period, t, team, holder, "shot", (x, y), (ex, ey), outcome)
                t += 1
                if outcome == "off_target":
                    return t + rng.randint(25, 40), opp, "goal_kick", 6, 50
                if rng.random() < 0.45:  # parried or deflected behind
                    return t + rng.randint(30, 45), team, "corner", 99, ey
                if outcome == "saved":
                    return t + rng.randint(6, 12), opp, "keeper", *flip(ex, ey)
                return t + 1, opp, "interception", *flip(ex, ey)

            raise ValueError(action)

    # ---------------------------------------------------------- story moments

    def scripted(self, period, rows):
        """Write planted events. Each row is
        (mm:ss, team, shirt, type, start, end, outcome, is_assist, new_possession)."""
        for mmss, team, shirt, type_, start, end, outcome, assist, new in rows:
            self.add(period, clock(mmss), team, shirt, type_, start, end, outcome,
                     is_assist=assist, new_possession=new)

    def moment_big_miss(self):
        """1. 38', Merriden through ball, Dunmore shoots wide from 8 metres."""
        self.scripted(1, [
            ("37:51", RED, 2, "pass", (62, 0), (64, 12), "complete", False, True),  # throw-in
            ("37:55", RED, 7, "pass", (64, 12), (56, 44), "complete", False, False),
            ("38:00", RED, 8, "pass", (56, 44), (92, 50), "complete", False, False),
            ("38:03", RED, 9, "carry", (92, 50), (94, 48), "complete", False, False),
            ("38:04", RED, 9, "shot", (94, 48), (100, 40), "off_target", False, False),
        ])
        return clock("38:30"), BLUE, "goal_kick", 6, 50

    def moment_blue_goal(self):
        """2. 61', Okoro tackle, Quill down the left, Vane scores (0-1)."""
        self.scripted(2, [
            ("60:50", RED, 3, "pass", (48, 100), (52, 86), "complete", False, True),  # throw-in
            ("60:54", RED, 11, "pass", (52, 86), (50, 60), "complete", False, False),
            ("60:58", RED, 6, "carry", (50, 60), (56, 54), "lost", False, False),
            # Exactly as in match-story.md / data-format.md:
            ("61:04", BLUE, 4, "tackle", (44, 46), (44, 46), "won", False, True),
            ("61:07", BLUE, 4, "pass", (44, 46), (58, 70), "complete", False, False),
            ("61:10", BLUE, 11, "carry", (58, 70), (74, 76), "complete", False, False),
            ("61:13", BLUE, 11, "pass", (74, 76), (88, 52), "complete", True, False),
            ("61:14", BLUE, 9, "shot", (88, 52), (100, 50), "goal", False, False),
        ])
        return clock("62:10"), RED, "kickoff", 50, 50

    def moment_keeper_save(self):
        """3. 67', Renwick slips Vane through, Harwick saves low."""
        self.scripted(2, [
            ("66:50", BLUE, 2, "pass", (60, 0), (62, 14), "complete", False, True),  # throw-in
            ("66:54", BLUE, 7, "pass", (62, 14), (64, 40), "complete", False, False),
            ("67:01", BLUE, 10, "pass", (64, 40), (91, 55), "complete", False, False),
            ("67:03", BLUE, 9, "shot", (91, 55), (99, 52), "saved", False, False),
        ])
        # Harwick holds it and distributes.
        return clock("67:10"), RED, "keeper", *flip(99, 52)

    def moment_counter(self):
        """5. 74', Blue attack breaks down, Red go the length: Tovey (1-1)."""
        self.scripted(2, [
            ("73:52", BLUE, 3, "pass", (62, 100), (66, 88), "complete", False, True),  # throw-in
            ("73:56", BLUE, 11, "carry", (66, 88), (74, 80), "complete", False, False),
            ("74:01", BLUE, 11, "pass", (74, 80), (72, 64), "complete", False, False),
            ("74:06", BLUE, 10, "pass", (72, 64), (83, 62), "incomplete", False, False),
            # Exactly as in match-story.md:
            ("74:10", RED, 5, "interception", (17, 38), (17, 38), "won", False, True),
            ("74:12", RED, 5, "pass", (17, 38), (35, 30), "complete", False, False),
            ("74:14", RED, 8, "pass", (35, 30), (62, 22), "complete", False, False),
            ("74:16", RED, 7, "carry", (62, 22), (80, 30), "complete", False, False),
            ("74:21", RED, 7, "pass", (80, 30), (90, 47), "complete", True, False),
            ("74:22", RED, 10, "shot", (90, 47), (100, 46), "goal", False, False),
        ])
        return clock("75:20"), BLUE, "kickoff", 50, 50

    def moment_late_winner(self):
        """6. 89', Brannick down the right, Dunmore scores the winner (2-1)."""
        self.scripted(2, [
            ("89:20", RED, 2, "pass", (64, 0), (68, 10), "complete", False, True),  # throw-in
            ("89:23", RED, 7, "carry", (68, 10), (85, 12), "complete", False, False),
            ("89:29", RED, 7, "pass", (85, 12), (94, 52), "complete", True, False),
            ("89:30", RED, 9, "shot", (94, 52), (100, 47), "goal", False, False),
        ])
        return clock("90:30"), BLUE, "kickoff", 50, 50

    # ------------------------------------------------------------ whole match

    def build(self):
        # First half: Red kick off; ends at 45+1.
        self.play(1, 0, clock("37:45"), RED, "kickoff", 50, 50)
        nxt = self.moment_big_miss()
        self.play(1, nxt[0], clock("46:20"), *nxt[1:])

        # Second half: Blue kick off; ends at 90+3.
        self.play(2, clock("45:00"), clock("60:45"), BLUE, "kickoff", 50, 50)
        nxt = self.moment_blue_goal()
        self.play(2, nxt[0], clock("66:45"), *nxt[1:])
        nxt = self.moment_keeper_save()
        self.play(2, nxt[0], clock("73:47"), *nxt[1:])
        nxt = self.moment_counter()
        self.play(2, nxt[0], clock("89:15"), *nxt[1:])
        nxt = self.moment_late_winner()
        self.play(2, nxt[0], clock("93:30"), *nxt[1:])

        # Moment 4 (Red's late momentum) comes from PHASES, not a script.
        self.events.sort(key=lambda e: (e["period"], e["minute"], e["second"]))
        ids = {}
        for i, e in enumerate(self.events, start=1):
            e["event_id"] = i
            e["possession_id"] = ids.setdefault(e["possession_id"], len(ids) + 1)
        self.events = [{k: e[k] for k in FIELDS} for e in self.events]

        goals = {RED: 0, BLUE: 0}
        for e in self.events:
            if e["type"] == "shot" and e["outcome"] == "goal":
                goals[e["team"]] += 1
        assert goals == FINAL_SCORE, f"goals {goals} != story score {FINAL_SCORE}"
        return self.events


def main():
    events = MatchGenerator(SEED).build()
    match = {
        "match": {
            "home_team": RED,
            "away_team": BLUE,
            "final_score": FINAL_SCORE,
            "seed": SEED,
        },
        "events": events,
    }
    DATA_DIR.mkdir(exist_ok=True)
    with open(DATA_DIR / "match.json", "w", encoding="utf-8") as f:
        json.dump(match, f, indent=2)
    with open(DATA_DIR / "match.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(events)

    counts = {}
    for e in events:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    print(f"Wrote {len(events)} events in {events[-1]['possession_id']} possessions "
          f"to data/match.json and data/match.csv (seed {SEED})")
    print("Events by type: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    print(f"Final score: London Red {FINAL_SCORE[RED]} - {FINAL_SCORE[BLUE]} London Blue")


if __name__ == "__main__":
    main()
