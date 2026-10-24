"""The xT reference: the zone grid, its colour scale and one worked example.

One source of truth for every place the grid is shown:
- web/data/xt_grid.json, written by src/build_site.py (reference()), which
  the page's "What is xT?" panel draws;
- docs/xt-grid.svg and the block between the xt-reference markers in
  README.md, written by this script.

The values come from xt_model.GRID and the worked example is read from
data/match_xt.csv and data/key_moments.json (never changes either), so no
number here is typed by hand.

Run:  python src/xt_reference.py
"""

import json
import sys
from pathlib import Path

import key_moments
import xt_model

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SVG_PATH = ROOT / "docs" / "xt-grid.svg"
README_PATH = ROOT / "README.md"

CAPTION = "A simple distance-based model, not trained on real matches."
EXAMPLE_MINUTE = 26  # the threat-swing pass used as the worked example

# Binned, colour-blind-safe sequential scale (viridis, 7 steps). A zone's
# colour is the last step whose lower bound it reaches.
SCALE = [
    (0.0, "#440154"), (0.005, "#443983"), (0.01, "#31688e"), (0.02, "#21918c"),
    (0.05, "#35b779"), (0.1, "#90d743"), (0.2, "#fde725"),
]
DARK_STEPS = 3  # the first steps are dark: white text on them, black on the rest

README_START = "<!-- xt-reference:start (written by python src/xt_reference.py, do not edit by hand) -->"
README_END = "<!-- xt-reference:end -->"


# ------------------------------------------------------------ data

def scale() -> list:
    """[{min, max, colour, label}] for the legend; max is None on the last step."""
    out = []
    for i, (low, colour) in enumerate(SCALE):
        high = SCALE[i + 1][0] if i + 1 < len(SCALE) else None
        label = (f"below {high:g}" if i == 0 else f"{low:g} or more" if high is None
                 else f"{low:g} to {high:g}")
        out.append({"min": low, "max": high, "colour": colour, "label": label})
    return out


def step(v) -> int:
    return max(i for i, (low, _) in enumerate(SCALE) if v >= low)


def best_zones() -> list:
    top = max(max(col) for col in xt_model.GRID)
    return [[c, r] for c in range(xt_model.COLS) for r in range(xt_model.ROWS) if xt_model.GRID[c][r] == top]


def place(x, y) -> str:
    """Where a point is in words: channel and third (definitions in README.md).
    y = 0 is the attacker's right."""
    channel = "right" if y < 100 / 3 else "left" if y >= 200 / 3 else "centre"
    third = "defensive" if x < 100 / 3 else "middle" if x < 200 / 3 else "final"
    side = "the centre" if channel == "centre" else f"the {channel} wing"
    return f"{side} of the {third} third"


def worked_example(events=None, moments=None) -> dict:
    """The key pass of the threat-swing moment at EXAMPLE_MINUTE, with the
    values of the zones it went from and to. Exits unless exactly one event
    matches and its xt_added is the difference of those two values."""
    events = events if events is not None else key_moments.load(DATA_DIR / "match_xt.csv")
    if moments is None:
        moments = json.loads((DATA_DIR / "key_moments.json").read_text(encoding="utf-8"))["moments"]
    found = [m for m in moments if m["category"] == "biggest_threat_swing" and m["minute"] == EXAMPLE_MINUTE]
    if len(found) != 1:
        sys.exit(f"expected one threat swing in minute {EXAMPLE_MINUTE}, found {len(found)}")
    m = found[0]
    f = m["facts"]
    hits = [e for e in events if (e["period"], e["minute"], e["second"], e["team"], e["type"], e["xt_added"]) ==
            (m["period"], m["minute"], m["second"], m["team"], f["action_type"], f["xt_added"])]
    if len(hits) != 1:
        sys.exit(f"{m['id']}: expected one key event, found {len(hits)}")
    e = hits[0]
    start, end = xt_model.zone_of(e["start_x"], e["start_y"]), xt_model.zone_of(e["end_x"], e["end_y"])
    from_value, to_value = xt_model.GRID[start[0]][start[1]], xt_model.GRID[end[0]][end[1]]
    if round(to_value - from_value, 4) != e["xt_added"]:
        sys.exit(f"{m['id']}: xt_added {e['xt_added']} is not {to_value} - {from_value}")
    return {"moment_id": m["id"], "event_id": e["event_id"], "period": e["period"], "minute": e["minute"],
            "second": e["second"], "team": e["team"], "player": e["player"], "type": e["type"],
            "start": [e["start_x"], e["start_y"]], "end": [e["end_x"], e["end_y"]],
            "from_zone": xt_model.zone_label(e["start_x"], e["start_y"]), "from_value": from_value,
            "from_place": place(e["start_x"], e["start_y"]),
            "to_zone": xt_model.zone_label(e["end_x"], e["end_y"]), "to_value": to_value,
            "to_place": place(e["end_x"], e["end_y"]),
            "xt_added": e["xt_added"]}


def reference(events=None, moments=None) -> dict:
    """Content of web/data/xt_grid.json. values[col][row]: col 0 is the
    team's own goal line, row 0 the attacker's right (y = 0)."""
    return {"cols": xt_model.COLS, "rows": xt_model.ROWS, "top_value": xt_model.TOP_VALUE,
            "half_distance": xt_model.HALF_DISTANCE, "y_weight": xt_model.Y_WEIGHT,
            "values": xt_model.GRID, "best_zones": best_zones(), "scale": scale(),
            "dark_steps": DARK_STEPS, "caption": CAPTION, "example": worked_example(events, moments)}


# ------------------------------------------------------------ README image

def clock(ex) -> str:
    return f"{ex['minute']}:{ex['second']:02d}"


def alt_text(ref) -> str:
    ex = ref["example"]
    return (f"Heat map of the {ref['cols']} by {ref['rows']} xT zone grid, attacking left to right. Zone values "
            f"rise from below {SCALE[1][0]:g} in the team's own half to about {ref['top_value']:.2f} in the "
            f"central zones in front of goal, and halve every {ref['half_distance']} units further from goal. "
            f"An arrow shows the {clock(ex)} pass by {ex['player']} from zone {ex['from_zone']} "
            f"(value {ex['from_value']}) to zone {ex['to_zone']} (value {ex['to_value']}).")


def svg(ref) -> str:
    """docs/xt-grid.svg: a self-contained heat map with its own colours, so it
    reads the same on a light or dark README page."""
    W, H = 600, 388                     # pitch in px; y = 0 (attacker's right) at the bottom
    L, T = 24, 64
    cw, ch = W / ref["cols"], H / ref["rows"]
    X = lambda x: L + x * W / 100
    Y = lambda y: T + (100 - y) * H / 100
    ex = ref["example"]
    best = ref["best_zones"]
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="648" height="590" viewBox="0 0 648 590" '
        f'role="img" aria-labelledby="t d" font-family="system-ui, -apple-system, Segoe UI, Roboto, sans-serif">',
        f'<title id="t">xT zone values</title>',
        f'<desc id="d">{alt_text(ref)}</desc>',
        '<rect width="648" height="590" fill="#ffffff"/>',
        f'<text x="{L}" y="28" font-size="18" font-weight="700" fill="#0b0b0b">xT zone values '
        f'({ref["cols"]} × {ref["rows"]} grid)</text>',
        f'<text x="{L}" y="50" font-size="13" fill="#52514e">How likely possession in each zone is to lead '
        f'to a goal soon</text>',
    ]
    for c in range(ref["cols"]):
        for r in range(ref["rows"]):
            v = ref["values"][c][r]
            out.append(f'<rect x="{L + c * cw:.1f}" y="{T + (ref["rows"] - 1 - r) * ch:.1f}" width="{cw:.1f}" '
                       f'height="{ch:.1f}" fill="{SCALE[step(v)][1]}" shape-rendering="crispEdges"><title>c{c}r{r}: {v}</title></rect>')
    out.append(f'<rect x="{L}" y="{T}" width="{W}" height="{H}" fill="none" stroke="#0b0b0b" stroke-width="1"/>')
    out.append(f'<line x1="{L + W / 2}" y1="{T}" x2="{L + W / 2}" y2="{T + H}" stroke="#ffffff" '
               f'stroke-opacity="0.5" stroke-dasharray="4 4"/>')
    # Best zones: one outline round them and the label inside.
    cols = sorted({c for c, _ in best})
    rows = sorted({r for _, r in best})
    bx, by = L + cols[0] * cw, T + (ref["rows"] - 1 - rows[-1]) * ch
    bw, bh = len(cols) * cw, len(rows) * ch
    out.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="none" '
               f'stroke="#0b0b0b" stroke-width="2.5"/>')
    cx, cy = bx + bw / 2, by + bh / 2
    out.append(f'<text x="{cx:.1f}" y="{cy - 4:.1f}" font-size="13" text-anchor="middle" fill="#0b0b0b">about</text>')
    out.append(f'<text x="{cx:.1f}" y="{cy + 13:.1f}" font-size="14" font-weight="700" text-anchor="middle" '
               f'fill="#0b0b0b">{ref["top_value"]:.2f}</text>')
    # Goal and attacking direction.
    gh = 7.32 / 68 * H
    out.append(f'<rect x="{L + W}" y="{T + H / 2 - gh / 2:.1f}" width="5" height="{gh:.1f}" fill="#0b0b0b"/>')
    ay = T + H + 26
    out.append(f'<line x1="{L + W / 2 - 90}" y1="{ay}" x2="{L + W / 2 + 80}" y2="{ay}" stroke="#0b0b0b" '
               f'stroke-width="2"/>')
    out.append(f'<path d="M{L + W / 2 + 90},{ay} l-12,-6 v12 z" fill="#0b0b0b"/>')
    out.append(f'<text x="{L + W / 2}" y="{ay - 8}" font-size="13" text-anchor="middle" fill="#0b0b0b">'
               f'Attacking direction (goal on the right)</text>')
    # The worked example's pass.
    x1, y1, x2, y2 = X(ex["start"][0]), Y(ex["start"][1]), X(ex["end"][0]), Y(ex["end"][1])
    for colour, width in (("#0b0b0b", 5), ("#ffffff", 2.5)):
        out.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{colour}" '
                   f'stroke-width="{width}" stroke-linecap="round"/>')
    out.append(f'<circle cx="{x1:.1f}" cy="{y1:.1f}" r="5" fill="#ffffff" stroke="#0b0b0b" stroke-width="2"/>')
    out.append(f'<circle cx="{x2:.1f}" cy="{y2:.1f}" r="5" fill="#0b0b0b" stroke="#ffffff" stroke-width="2"/>')
    # Legend.
    ly = ay + 34
    out.append(f'<text x="{L}" y="{ly}" font-size="13" font-weight="700" fill="#0b0b0b">Zone value (xT)</text>')
    sw = W / len(ref["scale"])
    for i, s in enumerate(ref["scale"]):
        out.append(f'<rect x="{L + i * sw:.1f}" y="{ly + 8}" width="{sw - 4:.1f}" height="16" fill="{s["colour"]}" '
                   f'stroke="#0b0b0b" stroke-width="0.5"/>')
        out.append(f'<text x="{L + i * sw:.1f}" y="{ly + 40}" font-size="12" fill="#0b0b0b">{s["label"]}</text>')
    out.append(f'<text x="{L}" y="{ly + 64}" font-size="12" fill="#52514e">Line: the {clock(ex)} pass in the '
               f'worked example, from the white dot to the black dot.</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def readme_block(ref) -> str:
    ex = ref["example"]
    fmt = lambda p: f"({p[0]:g}, {p[1]:g})"
    return "\n".join([
        README_START,
        f"![{alt_text(ref)}](docs/xt-grid.svg)",
        "",
        f"*{ref['caption']}*",
        "",
        f"**Worked example, the {EXAMPLE_MINUTE}th-minute pass ({ex['moment_id']}):** at {clock(ex)}, "
        f"{ex['player']} passed from {fmt(ex['start'])} to {fmt(ex['end'])}.",
        "",
        "| | Zone | Zone value |",
        "|---|---|---|",
        f"| From | `{ex['from_zone']}` | {ex['from_value']:.4f} |",
        f"| To | `{ex['to_zone']}` | {ex['to_value']:.4f} |",
        f"| xT added | | {ex['to_value']:.4f} − {ex['from_value']:.4f} = **+{ex['xt_added']:.4f}** |",
        README_END,
    ])


def readme_with_block(text, ref) -> str:
    """README text with the block replaced, or inserted under the definitions table."""
    block = readme_block(ref)
    if README_START in text:
        before, rest = text.split(README_START, 1)
        return before + block + rest.split(README_END, 1)[1]
    anchor = "| Shot-location value |"
    i = text.index(anchor)
    end = text.index("\n", i) + 1
    return text[:end] + "\n" + block + "\n" + text[end:]


def main():
    ref = reference()
    SVG_PATH.write_text(svg(ref), encoding="utf-8", newline="\n")
    print(f"Wrote {SVG_PATH.relative_to(ROOT)}")
    text = README_PATH.read_text(encoding="utf-8")
    new = readme_with_block(text, ref)
    if new != text:
        README_PATH.write_text(new, encoding="utf-8", newline="")
        print(f"Updated the xT block in {README_PATH.relative_to(ROOT)}")
    else:
        print(f"{README_PATH.relative_to(ROOT)} already up to date")


if __name__ == "__main__":
    main()
