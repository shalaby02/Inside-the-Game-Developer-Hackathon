# Teams

Both teams and all players are made up. In `data/match.json`, `team` + `shirt_number` identifies a player. The `player` field must still use these names exactly as written.

No substitutes: the same 11 players play the whole match.

## London Red (`london_red`): 4-4-2, home

| No. | Name | Position |
|---|---|---|
| 1 | Ellis Harwick | Goalkeeper (GK) |
| 2 | Jonah Pellow | Right back (RB) |
| 4 | Ade Fenwright | Centre back (CB) |
| 5 | Rory Calloway | Centre back (CB) |
| 3 | Kofi Ashdown | Left back (LB) |
| 7 | Theo Brannick | Right midfield (RM) |
| 8 | Luca Merriden | Central midfield (CM) |
| 6 | Idris Stanbury | Central midfield (CM) |
| 11 | Femi Oakhurst | Left midfield (LM) |
| 10 | Rafael Tovey | Striker (ST) |
| 9 | Cass Dunmore | Striker (ST) |

## London Blue (`london_blue`): 4-3-3, away

| No. | Name | Position |
|---|---|---|
| 1 | Bram Hollis | Goalkeeper (GK) |
| 2 | Yusuf Calder | Right back (RB) |
| 5 | Owen Strand | Centre back (CB) |
| 6 | Matteo Lisk | Centre back (CB) |
| 3 | Jamal Prewitt | Left back (LB) |
| 4 | Sam Okoro | Defensive midfield (DM) |
| 8 | Felix Ardent | Central midfield (CM) |
| 10 | Kai Renwick | Central midfield (CM) |
| 7 | Tobi Wexley | Right wing (RW) |
| 11 | Dario Quill | Left wing (LW) |
| 9 | Niko Vane | Striker (ST) |

Positions help the generator place players realistically. For example, a left winger's events are mostly at high `y` (the attacker's left side), and a centre back's are mostly at low `x`.
