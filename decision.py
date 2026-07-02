"""
decision.py — Solar Spill Phase 2
Turns a live QLD price + demand reading into:
  1. A charge/wait recommendation
  2. A Grid Health Score (1-10)

Thresholds are informed by the real dataset captured 2026-06-27:
  $32/MWh midday solar low  ->  $130/MWh evening peak
  demand ranged roughly 6,800 - 7,474 MW that Saturday.

See DECISIONS.md for why these numbers were chosen.
"""

# --- Thresholds (tunable) ---------------------------------------------------
CHEAP_PRICE   = 50.0    # $/MWh — below this, charging is worthwhile
PEAK_PRICE    = 100.0   # $/MWh — above this, grid is clearly expensive/stressed
HIGH_DEMAND   = 8000.0  # MW    — statewide demand we treat as "grid busy"
LOW_DEMAND    = 6500.0  # MW    — statewide demand we treat as "grid relaxed"


def decide(price, demand):
    """
    price  : current QLD spot price in $/MWh (can be negative)
    demand : current QLD demand in MW
    Returns a dict with the recommendation, the health score, and a reason.
    """

    # --- 1. The charge/wait call is driven mainly by PRICE ------------------
    if price < 0:
        action = "CHARGE"
        reason = "Negative price — solar oversupply, grid is paying you to take power."
    elif price < CHEAP_PRICE:
        action = "CHARGE"
        reason = f"Cheap window (< ${CHEAP_PRICE:.0f}/MWh)."
    else:
        action = "WAIT"
        reason = f"Price ${price:.0f}/MWh is above the cheap threshold — hold off."

    # --- 2. The Grid Health Score (1-10) blends PRICE and DEMAND ------------
    # Higher score = better time to charge (cheap + relaxed grid).
    score = grid_health_score(price, demand)

    # A high-demand warning rides alongside the score without flipping the
    # decision on its own. This is the early-warning signal for Phase 3.
    demand_note = ""
    if demand > HIGH_DEMAND:
        demand_note = f" (Heads up: statewide demand {demand:.0f} MW is high.)"

    return {
        "action": action,
        "score": score,
        "reason": reason + demand_note,
    }


def grid_health_score(price, demand):
    """
    Returns an integer 1-10.
    10 = cheapest / most relaxed grid (best time to charge)
     1 = expensive / most stressed grid (worst time to charge)

    Built from two sub-scores (price and demand) so that neither one
    alone dominates. This graduated signal is what lets Phase 3 stagger
    charging instead of every charger flipping on at the same instant.
    """

    # --- Price sub-score (0-1): cheaper = higher ---------------------------
    if price < 0:
        price_component = 1.0                      # negative price is the best case
    elif price >= PEAK_PRICE:
        price_component = 0.0                       # at/above peak = worst case
    else:
        # Linearly map price 0 -> PEAK_PRICE onto 1.0 -> 0.0
        price_component = 1.0 - (price / PEAK_PRICE)

    # --- Demand sub-score (0-1): more relaxed = higher ---------------------
    if demand <= LOW_DEMAND:
        demand_component = 1.0
    elif demand >= HIGH_DEMAND:
        demand_component = 0.0
    else:
        # Linearly map demand LOW -> HIGH onto 1.0 -> 0.0
        demand_component = 1.0 - (demand - LOW_DEMAND) / (HIGH_DEMAND - LOW_DEMAND)

    # --- Blend: price weighted a bit heavier than demand -------------------
    # Price is the sharper signal of "should I charge"; demand is the
    # slower-moving stress warning. 60/40 split.
    blended = 0.6 * price_component + 0.4 * demand_component

    # Map the 0.0-1.0 blend onto an integer 1-10.
    score = round(1 + blended * 9)
    return max(1, min(10, score))   # clamp to stay safely inside 1-10


# --- Quick self-test when run directly --------------------------------------
if __name__ == "__main__":
    # A few scenarios pulled from / around your real dataset.
    tests = [
        (-20, 6200),   # negative price, relaxed grid  -> ideal
        (32,  6800),   # your midday solar low
        (49,  7000),   # just under the cheap line
        (75,  7200),   # moderate, should wait
        (130, 7474),   # your evening peak
        (40,  8200),   # cheap price BUT high demand — watch the score
    ]
    print(f"{'price':>6} {'demand':>7}  {'action':<7} {'score':>5}  reason")
    print("-" * 80)
    for price, demand in tests:
        d = decide(price, demand)
        print(f"{price:>6} {demand:>7}  {d['action']:<7} {d['score']:>5}  {d['reason']}")
