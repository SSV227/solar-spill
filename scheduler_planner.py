"""
scheduler_planner.py — Solar Spill

The deadline-aware charge planner.

The user plugs in when they get home and sets a "full by" deadline. Rather than
charging immediately (naive) or gating on a fixed price threshold, this planner
looks across the WHOLE available window and charges only during the cheapest
intervals needed to meet the deadline.

This is the "oracle" version: it assumes the prices across the window are known.
That is exactly right for a SIMULATION replaying a real captured day (we already
have the prices), and it also gives the theoretical-best benchmark. A live
deployment would swap in AEMO short-term forecasts + an urgency override; that
is noted as future work, not built here.

Energy need is given physically as kWh required + charger power (kW); the planner
converts that to a number of 5-minute intervals it must charge for.
"""

import math
import pandas as pd

INTERVAL_MINUTES = 5
INTERVALS_PER_HOUR = 60 / INTERVAL_MINUTES   # 12


def intervals_needed(kwh_needed, charger_kw):
    """
    Convert a physical energy requirement into a whole number of 5-min intervals.

    Energy delivered in one interval = charger_kw * (5/60) hours  [kWh].
    Round UP so we never under-deliver and miss the deadline.
    """
    kwh_per_interval = charger_kw * (INTERVAL_MINUTES / 60)
    return math.ceil(kwh_needed / kwh_per_interval), kwh_per_interval


def plan_charge(window_df, kwh_needed, charger_kw):
    """
    window_df : a DataFrame of the intervals available in the plug-in -> deadline
                window, with columns 'wall_clock', 'price_mwh', 'demand_mw'.
                (Caller is responsible for slicing to the window.)
    kwh_needed, charger_kw : the car's energy requirement and charge speed.

    Returns a dict describing the smart plan and the naive baseline for comparison.
    """
    need, kwh_per_interval = intervals_needed(kwh_needed, charger_kw)
    available = len(window_df)

    # Can the deadline even be met? (Not enough intervals in the window.)
    deadline_met = need <= available

    # --- SMART plan: charge during the cheapest `need` intervals -------------
    # Rank the whole window by price (cheapest first) and take the top `need`.
    ranked = window_df.sort_values("price_mwh", kind="mergesort")  # stable sort
    smart = ranked.head(need)

    # --- NAIVE baseline: charge immediately on plug-in, back-to-back ---------
    naive = window_df.head(need)

    # --- Cost of each plan --------------------------------------------------
    # cost = sum over chosen intervals of  price($/MWh) * energy(MWh)
    mwh_per_interval = kwh_per_interval / 1000
    smart_cost = (smart["price_mwh"] * mwh_per_interval).sum()
    naive_cost = (naive["price_mwh"] * mwh_per_interval).sum()

    return {
        "intervals_needed": need,
        "intervals_available": available,
        "hours_needed": need / INTERVALS_PER_HOUR,
        "deadline_met": deadline_met,
        "smart_cost": smart_cost,
        "naive_cost": naive_cost,
        "smart_intervals": smart.sort_values("wall_clock"),
        "naive_intervals": naive.sort_values("wall_clock"),
        "smart_avg_price": smart["price_mwh"].mean(),
        "naive_avg_price": naive["price_mwh"].mean(),
    }


# --- Demo / self-test on the real captured data -----------------------------
if __name__ == "__main__":
    d = pd.read_csv("qld_decisions.csv")
    d["wall_clock"] = pd.to_datetime(d["wall_clock"])

    # Scenario: plug in Thu 9pm, want it full by Fri 7am. 40 kWh on a 7 kW charger.
    plug_in = pd.Timestamp("2026-07-02 21:00")
    deadline = pd.Timestamp("2026-07-03 07:00")
    kwh_needed = 40
    charger_kw = 7

    window = d[(d.wall_clock >= plug_in) & (d.wall_clock < deadline)].copy()

    result = plan_charge(window, kwh_needed, charger_kw)

    print(f"Plug in: {plug_in:%a %H:%M}   Deadline: {deadline:%a %H:%M}")
    print(f"Need {kwh_needed} kWh on a {charger_kw} kW charger "
          f"= {result['hours_needed']:.1f} h "
          f"({result['intervals_needed']} intervals)")
    print(f"Window has {result['intervals_available']} intervals available.")
    print(f"Deadline achievable: {result['deadline_met']}")
    print()

    print(f"{'':12} {'avg price':>10} {'rel. cost':>10}")
    print("-" * 36)
    print(f"{'NAIVE (5pm)':12} ${result['naive_avg_price']:>8.2f} "
          f"${result['naive_cost']:>9.3f}")
    print(f"{'SMART':12} ${result['smart_avg_price']:>8.2f} "
          f"${result['smart_cost']:>9.3f}")
    saving = (1 - result['smart_cost'] / result['naive_cost']) * 100
    print(f"\nSmart plan is {saving:.0f}% cheaper than charging on plug-in.")

    print("\nHours the SMART plan chose to charge:")
    chosen = result["smart_intervals"]
    # Compress consecutive picks into readable blocks
    times = chosen["wall_clock"].dt.strftime("%H:%M").tolist()
    print("  " + ", ".join(times[:8]) + (" ..." if len(times) > 8 else ""))
    print(f"  (price range of chosen intervals: "
          f"${chosen.price_mwh.min():.2f} to ${chosen.price_mwh.max():.2f})")
