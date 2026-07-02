# DECISIONS.md

A running record of *why* Solar Spill is built the way it is — not just what
the code does. The reasoning matters as much as the code for anyone reviewing
this project.

---

## Phase 2 — the decision logic

### The core split: decision vs. health score

The system produces two separate outputs from each price/demand reading:

1. **A charge/wait decision** — driven only by price.
2. **A Grid Health Score (1–10)** — blends price and demand.

They are deliberately kept apart. The decision answers *"should this car
charge right now?"* The score answers *"how much slack does the grid have?"*
These are different questions and conflating them causes the exact problem the
project exists to prevent (see "Why not a hard demand gate" below).

### Threshold: charge below $50/MWh

Chosen from the real dataset captured 2026-06-27 (Saturday):

- Midday solar low: **~$32/MWh**
- Evening peak: **~$130/MWh**

$50 sits above the cheap midday floor but well below the evening peak, so it
cleanly separates "genuinely cheap solar-surplus power" from "everyday and peak
pricing." Negative prices (grid oversupplied, effectively paying you to take
power) are treated as an even stronger charge signal.

**Caveat, on the record:** these numbers come from *weekend* data. Saturday
understates the weekday evening EV peak, so a weekday capture is still needed to
properly calibrate. The thresholds live as constants at the top of `decision.py`
precisely so they can be re-tuned once weekday data exists.

### Why not a hard demand gate

The obvious first design is: *"wait while statewide demand is high, charge the
moment it drops."* It was rejected for two reasons.

1. **Statewide demand is a loose proxy for local load.** The ~8,000 MW figure is
   *all of Queensland*, not one street's transformer. Wholesale/statewide
   conditions and a local transformer's capacity are not the same thing — the
   whole project rests on that distinction.

2. **A shared hard threshold makes the coordinated spike worse.** If every
   charger runs "wait while demand is high, charge the instant it drops," they
   all switch on at the same second demand dips below the line. That is a
   synchronised on-switch — the transformer spike, just triggered by demand
   instead of price. A sharp threshold everyone shares is the enemy.

So demand does **not** flip the decision on its own. Instead it feeds the health
score as a graduated signal.

### How the health score is built

Two sub-scores, each 0–1:

- **Price sub-score** — cheaper = higher (negative price = 1.0, at/above the
  $100/MWh peak = 0.0, linear in between).
- **Demand sub-score** — more relaxed = higher (≤6,500 MW = 1.0, ≥8,000 MW =
  0.0, linear in between).

Blended **60% price / 40% demand**, then mapped to an integer 1–10. Price is
weighted heavier because it is the sharper "should I charge" signal; demand is
the slower-moving stress warning. The blend is what makes the score *graduated*
rather than a cliff — and the graduated shape is the whole point (see below).

### What the score is actually for ("then what?")

Fair question: in Phase 2, with a single car, the score does not change any
behaviour — it is a readout, not a lever. That is intentional and stated
plainly here rather than dressed up.

The score's real job arrives in **Phase 3**, where it becomes the **stagger
dial** across many homes. Instead of a hard on/off, each car uses the score to
set the *probability* it starts charging in a given 5-minute window:

- High score (grid wide open) → high chance to start now.
- Low score (grid getting stressed) → low chance; most cars roll the dice and
  wait for the next window.

Run that across ~100 cars and they self-spread across the cheap period instead
of all slamming on at once. The randomness is what breaks the synchronised
spike. So the score is Phase 3's fuel; Phase 2 is where it is built and
validated. It is a deliberate signal here, with a defined consumer downstream —
not decoration.

---
