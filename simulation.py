"""
Solar Spill - Phase 3: Suburb Simulation
=========================================

Question this phase answers:
    If a whole suburb of EVs charges "smartly" off the SAME price signal,
    do they help the local transformer, or do they all pile into the same
    cheap hours and cause a NEW coordinated spike?

    And: does the two-layer design (deadline-aware planner + health-score
    staggering) actually flatten that spike while still hitting deadlines
    and staying cheap?

What it does:
    - Builds a fleet of ~100 EV homes on ONE shared distribution transformer.
    - Replays real QLD 5-minute price + demand data (drop in qld_decisions.csv),
      or a realistic synthetic day if the CSV isn't present.
    - Runs four charging strategies and measures the transformer load:
        1. naive_plugin  - charge full-power the moment you plug in ("dumb")
        2. fixed_2300    - everyone starts at 11pm ("Tesla default")
        3. smart_greedy  - each car runs the oracle planner, picks THE cheapest
                           intervals (Layer 1 only) -> everyone collides
        4. smart_stagger - Layer 1 + Layer 2: health-score-weighted stochastic
                           pick spreads colliding cars across the cheap window
    - Repeats the key comparison with a battery-saturation scenario to answer
      "won't home batteries fix this?" (spoiler: the 60kWh EV is the elephant,
       the 10kWh battery is the handbag).

The per-car planner here mirrors scheduler_planner.py. In the repo you can
replace plan_greedy() with `from scheduler_planner import plan_cheapest_intervals`
so the simulation literally runs the same engine as the live scheduler.

Author: Sritam (SSV227/solar-spill)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------

INTERVAL_MIN = 5                      # AEMO dispatch interval = 5 min
INTERVALS_PER_HOUR = 60 // INTERVAL_MIN


@dataclass
class Config:
    n_homes: int = 100               # EV-owning homes on the shared transformer
    seed: int = 227                  # reproducible fleets (SSV227 :)

    # Transformer / local network
    transformer_kva: float = 500.0   # shared distribution transformer rating
    admd_peak_kw: float = 2.2        # after-diversity max demand per home (evening)
    admd_base_kw: float = 0.45       # overnight baseline per home

    # Charger + EV fleet
    charger_kw: float = 7.4          # single-phase 32A home AC (default)
    batt_mean_kwh: float = 60.0      # ~Model 3 / mid EV
    batt_spread_kwh: float = 12.0
    arrival_soc: tuple = (0.25, 0.55)  # SoC when plugged in
    target_soc: float = 0.90

    # Behaviour timing (overnight commuter fleet)
    plugin_hour_mean: float = 18.0   # 6pm
    plugin_hour_sd: float = 1.0
    plugin_hour_clip: tuple = (16.5, 20.5)
    deadline_hour: float = 7.5       # 7:30am next day
    deadline_hour_sd: float = 0.5

    # Battery scenario
    battery_penetration: float = 0.50  # fraction of homes with a home battery
    home_battery_kwh: float = 10.0     # usable

    # Health score (recalibrated per Phase 2 findings)
    price_lo: float = 0.0            # $/MWh -> price sub-score = 1 (best) at/below
    price_hi: float = 150.0          # $/MWh -> price sub-score = 0 at/above
    demand_lo: float = 5500.0        # MW  -> demand sub-score = 1 at/below
    demand_hi: float = 7500.0        # MW  -> demand sub-score = 0 at/above
    price_weight: float = 0.60       # 60/40 blend

    data_csv: str = "qld_decisions.csv"
    out_dir: str = "phase3_out"


# ----------------------------------------------------------------------------
# Data: replay real captured data if present, else synthesise a realistic day
# ----------------------------------------------------------------------------

def health_score(price: np.ndarray, demand: np.ndarray, cfg: Config) -> np.ndarray:
    """1-10 Grid Health Score: 60/40 blend of price and demand sub-scores.
    Each sub-score is a clamped linear interpolation (1 = healthy, 0 = stressed).
    Matches decision.py, with the Phase-2 recalibrated demand band."""
    price_sub = np.clip((cfg.price_hi - price) / (cfg.price_hi - cfg.price_lo), 0, 1)
    demand_sub = np.clip((cfg.demand_hi - demand) / (cfg.demand_hi - cfg.demand_lo), 0, 1)
    blend = cfg.price_weight * price_sub + (1 - cfg.price_weight) * demand_sub
    return 1 + 9 * blend  # scale 0..1 -> 1..10


def synthetic_replay(cfg: Config) -> pd.DataFrame:
    """A realistic QLD1 weekday at 5-min resolution, matching the captured
    characteristics: demand peaks ~7,520 MW early evening and never hits 8,000;
    solar drives a cheap/negative midday price window; overnight prices flatter."""
    # 36 hours starting 15:00 so an overnight window (plug ~18:00 -> 07:30) sits
    # fully inside the series with margin on both ends.
    start = pd.Timestamp("2026-07-03 15:00")
    n = 36 * INTERVALS_PER_HOUR
    dt = pd.date_range(start, periods=n, freq=f"{INTERVAL_MIN}min")
    hod = np.asarray(dt.hour + dt.minute / 60.0, dtype=float)  # hour-of-day 0..24

    # --- Demand (MW): smooth double-humped day, evening peak ~7520 at ~17:52 ---
    # Base trough ~5100 overnight, morning bump, midday moderated by solar, big
    # evening peak.
    def demand_curve(h):
        # gaussians for morning + evening humps, on a raised floor
        morning = 900 * np.exp(-((h - 8.0) ** 2) / (2 * 1.6 ** 2))
        evening = 2400 * np.exp(-((h - 17.9) ** 2) / (2 * 1.7 ** 2))
        midday_solar_dip = -450 * np.exp(-((h - 12.5) ** 2) / (2 * 2.0 ** 2))
        return 5150 + morning + evening + midday_solar_dip
    demand = demand_curve(hod)
    demand += np.random.default_rng(cfg.seed).normal(0, 30, n)  # small noise
    # nudge the single peak to ~7520
    demand = demand * (7520.0 / demand.max())

    # --- Price ($/MWh): correlated with demand, but solar crushes midday, and
    #     a couple of negative dips in the afternoon (the QLD phenomenon) ---
    rng = np.random.default_rng(cfg.seed + 1)
    price = 55 + 0.030 * (demand - 5150)          # demand-linked base
    # solar midday suppression 9:00-15:00
    solar = np.clip(np.cos((hod - 12.5) / 3.2 * (np.pi / 2)), 0, 1)
    price -= 85 * solar ** 2
    # sharp evening scarcity spikes 17:00-19:30
    price += 70 * np.exp(-((hod - 18.2) ** 2) / (2 * 0.9 ** 2))
    price += rng.normal(0, 4, n)
    # a few genuine negative intervals in the afternoon solar trough
    aft = (hod > 11.5) & (hod < 14.5)
    price[aft] -= 12
    price = np.maximum(price, -2.5)               # floor near captured -$2.50

    df = pd.DataFrame({"dt": dt, "price": price, "demand_mw": demand})
    df["health"] = health_score(df["price"].values, df["demand_mw"].values, cfg)
    df["hod"] = hod
    return df.reset_index(drop=True)


def load_replay(cfg: Config) -> pd.DataFrame:
    """Prefer the real captured CSV; fall back to synthetic. Column auto-detect
    keeps this robust to whatever your logger named things."""
    path = Path(cfg.data_csv)
    if not path.exists():
        print(f"[data] {path} not found -> using synthetic realistic replay.")
        return synthetic_replay(cfg)

    raw = pd.read_csv(path)
    cols = {c.lower(): c for c in raw.columns}

    def pick(*cands):
        for cand in cands:
            if cand in cols:
                return cols[cand]
        return None

    dt_c = pick("settlement_date", "settlementdate", "wall_clock", "timestamp",
                "time", "dt", "datetime")
    pr_c = pick("price_mwh", "price", "rrp", "rrp_$/mwh", "spot_price")
    dm_c = pick("demand_mw", "demand", "totaldemand", "total_demand")

    if dt_c is None or pr_c is None:
        print("[data] Could not find date/price columns -> synthetic replay. "
              f"Found columns: {list(raw.columns)}")
        return synthetic_replay(cfg)

    df = pd.DataFrame()
    df["dt"] = pd.to_datetime(raw[dt_c])
    df["price"] = pd.to_numeric(raw[pr_c], errors="coerce")
    df["demand_mw"] = (pd.to_numeric(raw[dm_c], errors="coerce")
                       if dm_c else np.nan)
    df = df.dropna(subset=["price"]).sort_values("dt").reset_index(drop=True)
    if df["demand_mw"].isna().all():
        df["demand_mw"] = 6000.0  # neutral if no demand column
    df["health"] = health_score(df["price"].values, df["demand_mw"].values, cfg)
    df["hod"] = df["dt"].dt.hour + df["dt"].dt.minute / 60.0
    print(f"[data] Loaded {len(df)} real intervals from {path.name}.")
    return df


# ----------------------------------------------------------------------------
# Fleet
# ----------------------------------------------------------------------------

def _nearest_idx_for_hour(df: pd.DataFrame, day0: pd.Timestamp, hour: float,
                          next_day: bool = False) -> int:
    target = day0.normalize() + pd.Timedelta(hours=hour)
    if next_day:
        target += pd.Timedelta(days=1)
    return int((df["dt"] - target).abs().values.argmin())


def _snap(df: pd.DataFrame, ts: pd.Timestamp) -> int:
    return int((df["dt"] - ts).abs().values.argmin())


def make_fleet(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    rng = np.random.default_rng(cfg.seed)
    n = cfg.n_homes
    day0 = df["dt"].iloc[0].normalize()
    data_start = df["dt"].iloc[0]

    plugin_hour = np.clip(
        rng.normal(cfg.plugin_hour_mean, cfg.plugin_hour_sd, n),
        *cfg.plugin_hour_clip)
    deadline_hour = rng.normal(cfg.deadline_hour, cfg.deadline_hour_sd, n)

    # Intended plug-in = evening of day0; deadline = next morning.
    plugin_ts = [day0 + pd.Timedelta(hours=float(h)) for h in plugin_hour]
    deadline_ts = [day0 + pd.Timedelta(days=1, hours=float(h)) for h in deadline_hour]

    # If the capture started AFTER the intended plug-in window (e.g. logging
    # began at 21:00), shift every plug-in later by a common offset so the
    # earliest lands just inside the data. This preserves the SPREAD of arrival
    # times (which is what matters for coincidence) without inventing readings
    # we don't have.
    earliest = min(plugin_ts)
    if earliest < data_start:
        shift = (data_start - earliest) + pd.Timedelta(minutes=5)
        plugin_ts = [t + shift for t in plugin_ts]
        print(f"[fleet] Capture starts {data_start:%a %H:%M}; plug-ins shifted "
              f"+{shift.total_seconds()/3600:.1f} h to sit inside the data.")

    cap = np.clip(rng.normal(cfg.batt_mean_kwh, cfg.batt_spread_kwh, n), 40, 85)
    arr_soc = rng.uniform(*cfg.arrival_soc, n)
    kwh_needed = np.maximum((cfg.target_soc - arr_soc) * cap, 0.0)
    charger = np.full(n, cfg.charger_kw)

    plug_idx = np.array([_snap(df, t) for t in plugin_ts])
    dead_idx = np.array([_snap(df, t) for t in deadline_ts])

    kwh_per_interval = charger * INTERVAL_MIN / 60.0
    intervals_needed = np.ceil(kwh_needed / kwh_per_interval).astype(int)
    has_batt = rng.random(n) < cfg.battery_penetration

    return pd.DataFrame({
        "cap_kwh": cap, "arrival_soc": arr_soc, "kwh_needed": kwh_needed,
        "charger_kw": charger, "kwh_per_interval": kwh_per_interval,
        "plug_idx": plug_idx, "dead_idx": dead_idx,
        "intervals_needed": intervals_needed, "has_battery": has_batt,
    })


# ----------------------------------------------------------------------------
# Per-car planners  ->  each returns a boolean charging mask over the grid
# ----------------------------------------------------------------------------

def plan_plugin(car, n_grid) -> np.ndarray:
    """Naive: charge full power from plug-in until done."""
    mask = np.zeros(n_grid, bool)
    a = car.plug_idx
    b = min(a + car.intervals_needed, n_grid)
    mask[a:b] = True
    return mask


def plan_fixed(car, df, n_grid, start_hour=23.0) -> np.ndarray:
    """Naive fixed schedule: everyone starts at the same clock time (11pm)."""
    day0 = df["dt"].iloc[0]
    start = _nearest_idx_for_hour(df, day0, start_hour)
    # if plug-in is after the fixed start, begin at plug-in instead
    start = max(start, car.plug_idx)
    mask = np.zeros(n_grid, bool)
    b = min(start + car.intervals_needed, n_grid)
    mask[start:b] = True
    return mask


def plan_greedy(car, prices, n_grid) -> np.ndarray:
    """LAYER 1 (oracle planner, = scheduler_planner.py): within [plug, deadline]
    rank intervals by price and charge during the cheapest N. No coordination
    -> every car that shares this window picks the SAME cheapest intervals."""
    mask = np.zeros(n_grid, bool)
    lo, hi = car.plug_idx, min(car.dead_idx, n_grid - 1)
    if hi <= lo:
        return plan_plugin(car, n_grid)
    window = np.arange(lo, hi + 1)
    order = window[np.argsort(prices[window], kind="stable")]
    chosen = order[: car.intervals_needed]
    mask[chosen] = True
    return mask


def plan_stagger(car, prices, health, n_grid, rng) -> np.ndarray:
    """LAYER 1 + LAYER 2: Layer 1 defines the healthy candidate window and the
    per-interval health weights; Layer 2 is a health-weighted RANDOM draw of the
    N intervals instead of the deterministic cheapest-N. Independent randomness
    per car -> the fleet self-spreads across the cheap window instead of all
    stacking on the single cheapest interval. Deadline still guaranteed (always
    N intervals inside the window). The health score is the probability dial."""
    mask = np.zeros(n_grid, bool)
    lo, hi = car.plug_idx, min(car.dead_idx, n_grid - 1)
    if hi <= lo:
        return plan_plugin(car, n_grid)
    window = np.arange(lo, hi + 1)
    need = min(car.intervals_needed, len(window))

    # weights favour healthy intervals; ** sharpens preference for cheap hours.
    w = np.clip(health[window], 0.01, None) ** 3
    w = w / w.sum()
    chosen = rng.choice(window, size=need, replace=False, p=w)
    mask[chosen] = True
    return mask


# ----------------------------------------------------------------------------
# Run a strategy across the whole fleet
# ----------------------------------------------------------------------------

def run_strategy(name, fleet, df, cfg, rng):
    n_grid = len(df)
    prices = df["price"].values
    health = df["health"].values

    ev_load = np.zeros(n_grid)                 # kW at the transformer from EVs
    costs = np.zeros(len(fleet))               # $ per charge
    deadline_met = np.zeros(len(fleet), bool)
    per_car_peak_sum = 0.0                     # sum of individual peaks (for CF)

    for i, car in fleet.iterrows():
        if name == "naive_plugin":
            mask = plan_plugin(car, n_grid)
        elif name == "fixed_2300":
            mask = plan_fixed(car, df, n_grid, start_hour=23.0)
        elif name == "smart_greedy":
            mask = plan_greedy(car, prices, n_grid)
        elif name == "smart_stagger":
            mask = plan_stagger(car, prices, health, n_grid, rng)
        else:
            raise ValueError(name)

        ev_load += mask * car.charger_kw
        per_car_peak_sum += car.charger_kw if mask.any() else 0.0

        # did all charging land before the deadline?
        last_on = np.where(mask)[0]
        deadline_met[i] = (len(last_on) > 0 and last_on.max() <= car.dead_idx)

        # cost: energy each interval (kWh) * price ($/MWh -> $/kWh) 
        e_kwh = mask * car.kwh_per_interval
        costs[i] = np.sum(e_kwh * prices / 1000.0)

    return {
        "name": name, "ev_load": ev_load, "costs": costs,
        "deadline_met": deadline_met, "per_car_peak_sum": per_car_peak_sum,
    }


# ----------------------------------------------------------------------------
# Baseline household load at the transformer  (NOT the state MW demand!)
# ----------------------------------------------------------------------------

def baseline_load(df, cfg, with_batteries=False):
    """Local non-EV household load in kW at the transformer. Shaped like a
    domestic day (morning + evening humps). With batteries, ~half the evening
    household load is shaved (batteries discharge to cover the house) - but this
    does NOTHING to the overnight EV charging draw."""
    hod = df["hod"].values
    morning = 0.35 * np.exp(-((hod - 7.5) ** 2) / (2 * 1.3 ** 2))
    evening = 1.0 * np.exp(-((hod - 18.5) ** 2) / (2 * 1.8 ** 2))
    per_home = cfg.admd_base_kw + (cfg.admd_peak_kw - cfg.admd_base_kw) * \
               (0.35 * morning + evening)
    load = per_home * cfg.n_homes

    if with_batteries:
        # batteries in `battery_penetration` homes cover their own evening load
        # (roughly 4pm-9pm) until ~10kWh is spent. Model as a shave of evening.
        evening_window = (hod >= 16) & (hod <= 21.5)
        shave_per_batt_home = np.where(evening_window,
                                       (cfg.admd_peak_kw - cfg.admd_base_kw) * evening, 0)
        n_batt = int(round(cfg.n_homes * cfg.battery_penetration))
        load = load - shave_per_batt_home * n_batt
    return load


# ----------------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------------

def summarise(result, baseline, cfg):
    total = baseline + result["ev_load"]
    peak = total.max()
    ev_peak = result["ev_load"].max()
    cf = ev_peak / result["per_car_peak_sum"] if result["per_car_peak_sum"] else 0
    overloaded = int(np.sum(total > cfg.transformer_kva))
    return {
        "strategy": result["name"],
        "total_peak_kw": peak,
        "ev_peak_kw": ev_peak,
        "coincidence_factor": cf,
        "overload_intervals": overloaded,
        "pct_of_rating": 100 * peak / cfg.transformer_kva,
        "avg_cost_$": result["costs"].mean(),
        "deadline_met_pct": 100 * result["deadline_met"].mean(),
    }


# ----------------------------------------------------------------------------
# Plots
# ----------------------------------------------------------------------------

INK = "#1a1a2e"
GRID = "#d9d9e3"
COLORS = {
    "naive_plugin": "#e63946",
    "fixed_2300":   "#f4a261",
    "smart_greedy": "#8d99ae",
    "smart_stagger":"#2a9d8f",
}
LABELS = {
    "naive_plugin": "Naive: charge on plug-in",
    "fixed_2300":   "Fixed 11pm (Tesla default)",
    "smart_greedy": "Smart, no stagger (Layer 1)",
    "smart_stagger":"Smart + stagger (Layer 1+2)",
}


def plot_strategies(df, results, baseline, cfg, path, xlim=None):
    fig, ax = plt.subplots(figsize=(12, 6.2))
    t = df["dt"]
    ax.fill_between(t, 0, baseline, color=GRID, alpha=0.7,
                    label="Household baseline (non-EV)", zorder=1)
    for r in results:
        total = baseline + r["ev_load"]
        ax.plot(t, total, color=COLORS[r["name"]], lw=2.1,
                label=LABELS[r["name"]], zorder=3)
    ax.axhline(cfg.transformer_kva, color=INK, ls="--", lw=1.4,
               label=f"Transformer rating ({cfg.transformer_kva:.0f} kVA)")
    ax.set_ylabel("Transformer load (kW)", color=INK)
    ax.set_title(f"Solar Spill Phase 3 — {cfg.n_homes} EV homes on one transformer\n"
                 "Same price signal, four charging strategies", color=INK)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %H:%M"))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=3))
    plt.setp(ax.get_xticklabels(), rotation=0, ha="center", fontsize=8)
    ax.grid(True, color=GRID, alpha=0.5)
    ax.legend(loc="upper left", fontsize=8.5, framealpha=0.95)
    ax.margins(x=0.01)
    if xlim:
        ax.set_xlim(xlim)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_signal_vs_local(df, greedy_res, baseline, cfg, path, xlim=None):
    """The money shot: cheapest STATE price interval is exactly where every
    smart-greedy car piles on and overloads the LOCAL transformer."""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True,
                                   gridspec_kw={"height_ratios": [1, 1.2]})
    t = df["dt"]
    ax1.plot(t, df["price"], color="#5661b3", lw=1.8)
    ax1.axhline(0, color="#999", lw=0.8)
    ax1.set_ylabel("QLD wholesale\nprice ($/MWh)", color=INK)
    ax1.set_title("Statewide price says 'cheap'  →  but the local transformer says 'stop'",
                  color=INK)
    ax1.grid(True, color=GRID, alpha=0.5)

    # where the fleet ACTUALLY converges = where smart-greedy EV load peaks
    spike = int(greedy_res["ev_load"].argmax())
    # the globally cheapest interval (usually midday solar) - unreachable overnight
    midday_min = int(df["price"].values.argmin())
    ax1.axvline(t.iloc[spike], color="#e63946", ls=":", lw=1.5)
    ax1.annotate("midday solar min\n(unreachable for\novernight cars)",
                 xy=(t.iloc[midday_min], df["price"].iloc[midday_min]),
                 xytext=(t.iloc[midday_min], df["price"].max() * 0.55),
                 fontsize=7.5, ha="center", color="#5661b3",
                 arrowprops=dict(arrowstyle="->", color="#5661b3", lw=1))

    total = baseline + greedy_res["ev_load"]
    ax2.fill_between(t, 0, baseline, color=GRID, alpha=0.7, label="Household baseline")
    ax2.plot(t, total, color=COLORS["smart_greedy"], lw=2.2,
             label="Smart-greedy total load")
    ax2.axhline(cfg.transformer_kva, color=INK, ls="--", lw=1.4,
                label=f"Transformer rating")
    ax2.axvline(t.iloc[spike], color="#e63946", ls=":", lw=1.5,
                label="Cheapest reachable interval → everyone piles on")
    ax2.set_ylabel("Local transformer\nload (kW)", color=INK)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%a %H:%M"))
    ax2.xaxis.set_major_locator(mdates.HourLocator(interval=3))
    ax2.grid(True, color=GRID, alpha=0.5)
    ax2.legend(loc="upper left", fontsize=8.5)
    ax2.margins(x=0.01)
    if xlim:
        ax1.set_xlim(xlim)
        ax2.set_xlim(xlim)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_battery(df, no_batt, with_batt, base_no, base_with, cfg, path, xlim=None):
    fig, ax = plt.subplots(figsize=(12, 6.2))
    t = df["dt"]
    ax.plot(t, base_no + no_batt["ev_load"], color="#8d99ae", lw=2.0,
            label="No batteries — smart-greedy total")
    ax.plot(t, base_with + with_batt["ev_load"], color="#2a9d8f", lw=2.0,
            label=f"{int(cfg.battery_penetration*100)}% homes w/ 10kWh battery — smart-greedy total")
    ax.fill_between(t, 0, base_no, color=GRID, alpha=0.5, label="Baseline (no batt)")
    ax.axhline(cfg.transformer_kva, color=INK, ls="--", lw=1.4,
               label="Transformer rating")
    ax.set_ylabel("Transformer load (kW)", color=INK)
    ax.set_title("“Won't home batteries fix this?”  —  The EV is the elephant, the battery is the handbag\n"
                 "Batteries shave the evening household hump; the overnight EV spike is untouched",
                 color=INK, fontsize=11)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %H:%M"))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=3))
    ax.grid(True, color=GRID, alpha=0.5)
    ax.legend(loc="upper left", fontsize=8.5)
    ax.margins(x=0.01)
    if xlim:
        ax.set_xlim(xlim)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main(cfg: Config = None):
    cfg = cfg or Config()
    out = Path(cfg.out_dir)
    out.mkdir(exist_ok=True)

    df = load_replay(cfg)
    fleet = make_fleet(df, cfg)
    base = baseline_load(df, cfg, with_batteries=False)

    strategies = ["naive_plugin", "fixed_2300", "smart_greedy", "smart_stagger"]
    results = []
    rows = []
    for s in strategies:
        rng = np.random.default_rng(cfg.seed + 100)  # fresh RNG per strategy
        r = run_strategy(s, fleet, df, cfg, rng)
        results.append(r)
        rows.append(summarise(r, base, cfg))

    summary = pd.DataFrame(rows)

    # peak reduction vs the worst naive baseline
    worst = summary["total_peak_kw"].max()
    summary["peak_reduction_vs_worst_%"] = 100 * (worst - summary["total_peak_kw"]) / worst

    # ---- battery scenario (smart-greedy, with vs without batteries) ----
    base_batt = baseline_load(df, cfg, with_batteries=True)
    rng = np.random.default_rng(cfg.seed + 100)
    greedy_no = run_strategy("smart_greedy", fleet, df, cfg, rng)
    greedy_with = greedy_no  # EV load identical; only baseline changes
    batt_rows = [
        {"scenario": "no batteries",
         "total_peak_kw": (base + greedy_no["ev_load"]).max(),
         "ev_spike_kw": greedy_no["ev_load"].max()},
        {"scenario": f"{int(cfg.battery_penetration*100)}% homes w/ battery",
         "total_peak_kw": (base_batt + greedy_with["ev_load"]).max(),
         "ev_spike_kw": greedy_with["ev_load"].max()},
    ]
    battery_summary = pd.DataFrame(batt_rows)

    # ---- focus plots on the window where EVs are actually active ----
    any_ev = np.zeros(len(df), bool)
    for r in results:
        any_ev |= r["ev_load"] > 0
    act = np.where(any_ev)[0]
    lo_t = df["dt"].iloc[act[0]] - pd.Timedelta(minutes=45)
    hi_t = df["dt"].iloc[act[-1]] + pd.Timedelta(hours=1)
    xlim_tight = (lo_t, hi_t)
    # wider view for the price panel so the (unreachable) midday solar min shows
    right = min(df["dt"].iloc[act[-1]] + pd.Timedelta(hours=12), df["dt"].iloc[-1])
    xlim_wide = (lo_t, right)

    # ---- outputs ----
    plot_strategies(df, results, base, cfg, out / "strategies.png", xlim=xlim_tight)
    greedy_res = next(r for r in results if r["name"] == "smart_greedy")
    plot_signal_vs_local(df, greedy_res, base, cfg, out / "signal_vs_local.png",
                         xlim=xlim_wide)
    plot_battery(df, greedy_no, greedy_with, base, base_batt, cfg,
                 out / "battery_scenario.png", xlim=xlim_tight)
    summary.to_csv(out / "summary.csv", index=False)

    # ---- print ----
    pd.set_option("display.width", 140)
    pd.set_option("display.max_columns", None)
    print("\n================ STRATEGY COMPARISON ================")
    show = summary[["strategy", "total_peak_kw", "pct_of_rating",
                    "coincidence_factor", "overload_intervals",
                    "avg_cost_$", "deadline_met_pct",
                    "peak_reduction_vs_worst_%"]].copy()
    for c in ["total_peak_kw", "pct_of_rating", "peak_reduction_vs_worst_%"]:
        show[c] = show[c].round(1)
    show["coincidence_factor"] = show["coincidence_factor"].round(2)
    show["avg_cost_$"] = show["avg_cost_$"].round(2)
    show["deadline_met_pct"] = show["deadline_met_pct"].round(0)
    print(show.to_string(index=False))

    print("\n================ BATTERY SCENARIO (smart-greedy) ================")
    bs = battery_summary.copy()
    bs["total_peak_kw"] = bs["total_peak_kw"].round(1)
    bs["ev_spike_kw"] = bs["ev_spike_kw"].round(1)
    print(bs.to_string(index=False))
    print(f"\nTransformer rating: {cfg.transformer_kva:.0f} kVA | "
          f"Fleet: {cfg.n_homes} EVs | charger {cfg.charger_kw} kW\n")

    return summary, battery_summary


if __name__ == "__main__":
    main()