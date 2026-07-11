# Phase 3 — Suburb Simulation

**Question:** if a whole suburb charges "smartly" off the *same* price signal,
does it help the local transformer, or do all the cars pile into the same cheap
hours and cause a *new* coordinated spike? And does the two-layer design
(deadline-aware planner + health-score staggering) flatten that spike while
still hitting deadlines and staying cheap?

## Setup

- 100 EV homes on **one shared 500 kVA distribution transformer**.
- Replays real QLD 5-min price + demand (`qld_decisions.csv`), or a realistic
  synthetic day if the CSV isn't present.
- Household baseline load is modelled **separately** from statewide MW demand —
  this is the whole point: cheap statewide price ≠ spare *local* transformer
  capacity.

## Four strategies

| key | what it is |
|---|---|
| `naive_plugin` | charge full-power the second you plug in ("dumb") |
| `fixed_2300` | everyone starts at 11pm (Tesla default) |
| `smart_greedy` | each car runs the oracle planner, picks **the** cheapest N intervals — Layer 1 only |
| `smart_stagger` | Layer 1 + Layer 2: health-weighted **random** pick spreads colliding cars across the cheap window |

Then two **coordinated** strategies — the "solution" tier that actually sees the
local transformer (the first four only ever saw statewide price):

| key | what it is |
|---|---|
| `smart_decentral` | realistic: no central authority. Each car watches how loaded the box already is and backs off if it's crowded — unless its deadline forces it on. Reduces the spike; can't *guarantee* zero. |
| `smart_capped` | best case: a coordinator hands out charging slots cheapest-first but never exceeds what the transformer can carry. Guarantees zero overload by construction. |

## Headline result — REAL captured data (352 intervals, Thu 02→Sat 04 Jul; 100 EVs, 7.4 kW, 500 kVA)

Overnight commuter fleet, anchored to the fully-covered Thu-night window
(capture began 21:00, so plug-ins are shifted to start inside the data while
keeping the spread of arrival times).

| strategy | peak kW | % of rating | coincidence factor | overload intervals | avg cost | deadline met |
|---|---|---|---|---|---|---|
| naive_plugin | 755 | 151% | 0.96 | 38 | $1.86 | 100% |
| fixed_2300 | 778 | 156% | 0.99 | 45 | $1.79 | 100% |
| smart_greedy | 786 | 157% | **1.00** | 42 | $1.60 | 100% |
| smart_stagger | 570 | 114% | 0.71 | 11 | $1.86 | 100% |
| smart_decentral | 504 | 101% | 0.62 | **2** | $1.87 | 100% |
| **smart_capped** | **500** | **99.9%** | 0.61 | **0** | $1.78 | 100% |

**The problem:** `smart_greedy` hits coincidence factor **1.00** — naive "smart"
charging is a *perfect* coordinated spike. Every car reads the same prices, picks
the same cheapest interval, and all 100 charge at once — no safer than the dumb
11pm timer, it just moves the spike.

**The fix (the arc that matters):** as cars coordinate on the *local* transformer
instead of only the statewide price, the peak falls monotonically —
157% → 114% → 101% → 99.9%, and overloads 42 → 11 → 2 → **0**:

- `smart_stagger` spreads by *statewide* health, so it's capacity-blind and
  still leaves 11 overloads on the flat real-price night.
- `smart_decentral` (no central authority — each car reacts to how loaded the box
  already is) gets almost all the way: 101%, just **2** residual overloads from
  cars whose deadline forces them on at a crowded moment. This is what you could
  actually ship as a consumer app.
- `smart_capped` (a coordinator that never over-fills the box) **guarantees zero
  overloads**, packs the transformer to 99.9% of rating, *and* is the cheapest of
  the coordinated options ($1.78). This is the DNSP-run ideal.

All six keep **100% deadline compliance**. The takeaway: individual optimisation
(even staggered) can't protect the transformer; you need coordination *across*
homes — and even a fully decentralised version gets you 97% of the way, which is
the deployable middle ground.

## Key design decisions

- **Oracle planner (assumes prices known).** Legitimate here because we replay
  *already-captured* data — it's the theoretical-best benchmark. A live
  deployment uses AEMO forecasts + an urgency override; documented as future
  work, same as `scheduler_planner.py`.
- **Stagger = health-weighted stochastic draw, not a fixed offset.** Layer 1
  defines the healthy candidate window + weights (via the 1–10 Grid Health
  Score); Layer 2 samples N intervals from it at random per car. Independent
  randomness → the fleet self-spreads. Deadline is guaranteed because it always
  picks exactly N intervals inside the window. **No central coordinator.**
- **Coincidence factor is the metric that exposes the problem.** Peak kW alone
  hides it; CF = 1.00 is the smoking gun for "everyone responded to the same
  signal."
- **Battery scenario.** Batteries shave the *evening household* hump only; the
  overnight EV spike is byte-for-byte identical with 0% or 50% battery
  penetration. The 60 kWh EV is the elephant, the 10 kWh battery is the handbag.

## Honest limitations (→ next steps)

- `smart_capped` assumes a trusted central coordinator with authority over every
  car — realistic for a network-operator (DNSP) scheme, less so for a consumer
  app; `smart_decentral` is the app-shaped answer but leaves a couple of
  deadline-forced overloads. Closing that last gap (e.g. a light broadcast
  "transformer nearly full" signal) is the natural refinement.
- One transformer, homogeneous 7.4 kW chargers, single overnight commuter
  cohort. Daytime-flexible cars (that *can* reach the midday solar/negative
  window — richly captured on both days of real data) are the obvious next
  cohort — they'd show a second coordinated spike at noon.
- Capture began 21:00 Thu and Sat morning is sparse (Mac slept), so the fleet is
  anchored to the dense Thu-night window. A `caffeinate`d multi-day capture would
  let the fleet span its natural evening plug-in times.
- Prices are perfect-foresight (oracle). Live version needs forecast + urgency.
- pf ≈ 1 (kW ≈ kVA); baseline household shape is modelled, not metered.

## Run it

```bash
python3 simulation.py          # uses qld_decisions.csv if present, else synthetic
```

Outputs → `phase3_out/`: `strategies.png` (the problem), `coordination.png`
(the fix), `signal_vs_local.png`, `battery_scenario.png`, `summary.csv`.