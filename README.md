# Inside the Game — AI Match Recaps

A small multi-agent app built for the **Microsoft x Premier League "Inside the Game" Developer Hackathon**.

It takes a **synthetic football match**, measures how dangerous every pass and dribble was using a simple **Expected Threat (xT)** model, and then uses three AI agents to explain what happened:

| Agent | Job |
|---|---|
| 🔍 **Analyst** | Reads the xT numbers and picks out the key moments of the match |
| 🎙️ **Narrator** | Turns those moments into a match recap story |
| 🎯 **Personalizer** | Rewrites the recap for the reader: **analyst mode** (tactical, data-driven) or **casual fan mode** (fun, no jargon), in **two languages** |

The match data and the xT calculations are plain Python. The AI agents only *explain* the numbers and never invent them. The agents run on **Microsoft Foundry**.

## Status

🚧 Work in progress. See [PLAN.md](PLAN.md) for the 14-day build plan.

## How it works

```
Synthetic match → xT model → Analyst → Narrator → Personalizer → Recap
   (code)          (code)     (agent)    (agent)     (agent)
```

## Getting started

_Coming soon: setup and run instructions._

## Demo

_Coming soon: link to the 2-minute demo video._

## Note

All match data is synthetic (made up by a script). It is not real Premier League data.
