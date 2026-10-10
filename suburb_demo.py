"""
suburb_demo.py - Solar Spill ten-house demonstrator

Ten EVs on one shared transformer, replaying one real Queensland night from
qld_decisions.csv (2 July 2026, 21:00 onward). Two strategies, both computed
up front from the same price data:

  smart        Every car independently picks its own cheapest intervals
               before its deadline. They all read the same price feed, so they
               all pick the same hours. This is the Phase 3 "smart_greedy" case.

  coordinated  A coordinator hands out charging slots cheapest-first but never
               lets more than CAPACITY cars charge at once. Least-flexible cars
               are scheduled first so nobody misses their deadline. This is the
               Phase 3 "smart_capped" case, scaled down to ten houses.

The board polls /suburb and lights one LED per charging house.

Scaling note: Phase 3 used 100 homes on a 500 kVA transformer. Here, 10 homes
with a cap of 6 simultaneous 7 kW chargers keeps the same idea (the
transformer cannot carry every car at once) at a size you can see on a desk.
"""

import csv
import math
import time
from pathlib import Path

CSV_PATH = Path(__file__).parent / "qld_decisions.csv"

NUM_HOUSES = 10
CAPACITY = 6                 # max cars charging at once before "overload"
CHARGER_KW = 7.0
INTERVAL_HOURS = 5 / 60
SECONDS_PER_INTERVAL = 0.5   # replay speed: one night in about a minute

# One fixed set of households so every run is identical and repeatable.
# plug_in is an interval index from 21:00 (0 = 21:00, 12 = 22:00).
HOUSES = [
    {"plug_in": 0,  "kwh": 24},
    {"plug_in": 1,  "kwh": 30},
    {"plug_in": 2,  "kwh": 18},
    {"plug_in": 4,  "kwh": 28},
    {"plug_in": 5,  "kwh": 22},
    {"plug_in": 7,  "kwh": 26},
    {"plug_in": 9,  "kwh": 20},
    {"plug_in": 11, "kwh": 32},
    {"plug_in": 14, "kwh": 24},
    {"plug_in": 18, "kwh": 27},
]
DEADLINE_TIME = "07:00"      # everyone wants the car full by 7am


def load_night(csv_path=CSV_PATH):
    """Rows from the start of the capture up to the 7am deadline."""
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                rows.append({
                    "settlement": row["settlement_date"],
                    "price": float(row["price_mwh"]),
                })
            except (KeyError, ValueError):
                continue

    for i, row in enumerate(rows):
        if i > 0 and row["settlement"][11:16] == DEADLINE_TIME:
            return rows[: i + 1]
    return rows[:120]


def intervals_needed(kwh):
    return math.ceil(kwh / (CHARGER_KW * INTERVAL_HOURS))


def plan_smart(night):
    """Each car picks its own cheapest intervals. Nobody looks at anyone else."""
    deadline = len(night)
    plans = []
    for h in HOUSES:
        window = range(h["plug_in"], deadline)
        need = intervals_needed(h["kwh"])
        cheapest = sorted(window, key=lambda t: (night[t]["price"], t))[:need]
        plans.append(set(cheapest))
    return plans


def plan_coordinated(night):
    """Cheapest-first, but never more than CAPACITY cars in one interval."""
    deadline = len(night)
    load = [0] * deadline
    plans = [set() for _ in HOUSES]

    # Schedule the least flexible car first: smallest spare time.
    def slack(i):
        h = HOUSES[i]
        return (deadline - h["plug_in"]) - intervals_needed(h["kwh"])

    for i in sorted(range(len(HOUSES)), key=slack):
        h = HOUSES[i]
        need = intervals_needed(h["kwh"])
        window = sorted(range(h["plug_in"], deadline),
                        key=lambda t: (night[t]["price"], t))
        for t in window:
            if len(plans[i]) == need:
                break
            if load[t] < CAPACITY:
                plans[i].add(t)
                load[t] += 1
    return plans


def summarise(name, night, plans):
    """Peak, overloads and deadline check, for the self-test and the README."""
    loads = [sum(t in p for p in plans) for t in range(len(night))]
    met = sum(len(p) >= intervals_needed(h["kwh"])
              for p, h in zip(plans, HOUSES))
    cost = sum(night[t]["price"] * CHARGER_KW * INTERVAL_HOURS / 1000
               for p in plans for t in p) / len(HOUSES)
    return {
        "strategy": name,
        "peak_cars": max(loads),
        "overload_intervals": sum(l > CAPACITY for l in loads),
        "deadlines_met": f"{met}/{len(HOUSES)}",
        "avg_cost": round(cost, 2),
    }


class SuburbDemo:
    """Replays the night on a wall clock and reports which houses are on."""

    MODES = ("smart", "coordinated")

    def __init__(self, csv_path=CSV_PATH):
        self.night = load_night(csv_path)
        self.plans = {
            "smart": plan_smart(self.night),
            "coordinated": plan_coordinated(self.night),
        }
        self.mode = "smart"
        self.reset()

    def reset(self):
        self.started_at = time.time()

    def toggle(self):
        """Switch strategy and restart the night so the comparison is fair."""
        self.mode = "coordinated" if self.mode == "smart" else "smart"
        self.reset()
        return self.mode

    def state(self):
        elapsed = time.time() - self.started_at
        t = int(elapsed / SECONDS_PER_INTERVAL) % len(self.night)
        houses = [t in p for p in self.plans[self.mode]]
        on = sum(houses)
        return {
            "mode": self.mode,
            "sim_time": self.night[t]["settlement"],
            "price": self.night[t]["price"],
            "houses": houses,
            "charging_now": on,
            "capacity": CAPACITY,
            "overloaded": on > CAPACITY,
            "progress_pct": round(100 * (t + 1) / len(self.night)),
        }


if __name__ == "__main__":
    night = load_night()
    print(f"Night: {night[0]['settlement']} -> {night[-1]['settlement']} "
          f"({len(night)} intervals)\n")
    for name, planner in (("smart", plan_smart),
                          ("coordinated", plan_coordinated)):
        print(summarise(name, night, planner(night)))
