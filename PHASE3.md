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

## Headline result — REAL captured data (352 intervals, Thu 02→Sat 04 Jul; 100 EVs, 7.4 kW, 500 kVA)

Overnight commuter fleet, anchored to the fully-covered Thu-night window
(capture began 21:00, so plug-ins are shifted to start inside the data while
keeping the spread of arrival times).

| strategy | peak kW | % of rating | coincidence factor | overload intervals | avg cost | deadline met |
|---|---|---|---|---|---|---|
| naive_plugin | 755 | 151% | 0.96 | 38 | $1.86 | 100% |
| fixed_2300 | 778 | 156% | 0.99 | 45 | $1.79 | 100% |
| smart_greedy | 786 | 157% | **1.00** | 42 | $1.60 | 100% |
| smart_stagger | **570** | **114%** | 0.71 | 11 | $1.86 | 100% |

**The finding survives on real data:** `smart_greedy` hits coincidence factor
**1.00** — naive "smart" charging is a *perfect* coordinated spike. Every car
reads the same prices, picks the same cheapest interval, and all 100 charge at
once — no safer than the dumb 11pm timer, it just moves the spike. The
health-score stagger cuts the peak **~27%** and CF to 0.71.

**The honest twist (this is the strong interview point):** on the *synthetic*
day, stagger cleared **every** overload (0 left). On the **real** Thursday-night
data it only got down to **11** overload intervals — because the real overnight
price curve is *flat* (mostly $54–84, just a few $45 dips). There isn't a deep
cheap trough to spread 100 cars into, so health-weighted randomness still leaves
overlap. That exposes a real limitation: **the health score is derived from
*statewide* price+demand — it's blind to the *local* transformer.** Two cars
both picking a "healthy" $45 interval still stack on the same street. To
*guarantee* zero overloads you need Layer 2 to be **local-capacity-aware** — cars
spreading relative to how many are already drawing on *this* transformer. Which
is exactly the suburb-level coordinator that is the whole thesis. The real data
argues for the product better than the synthetic data did.

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

- **Stagger is capacity-blind (the big one).** Layer 2 spreads by *statewide*
  grid health, not by *local* transformer load, so on a flat price signal it
  can't clear every overload. Next tier: a `smart_coordinated` strategy where
  each car also sees how loaded *this* transformer already is at each interval →
  should drive overloads to 0. This is the actual Solar Spill coordinator.
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

Outputs → `phase3_out/`: `strategies.png`, `signal_vs_local.png`,
`battery_scenario.png`, `summary.csv`.
