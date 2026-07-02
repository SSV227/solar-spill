"""
scheduler.py — Solar Spill Phase 2
The live loop. Every 5 minutes it:
  1. Fetches the current QLD price + demand from AEMO
  2. Runs decision.py to get a charge/wait call + Grid Health Score
  3. Prints the decision to the screen
  4. Appends the whole reading (incl. the decision + score) to qld_decisions.csv

This is logger.py with a brain bolted on. It writes to a SEPARATE csv so the
Phase 1 dataset (qld_prices.csv) stays clean and frozen.
"""

import csv
import os
import time
from datetime import datetime

import requests

from decision import decide   # <-- our Phase 2 brain

# --- Config -----------------------------------------------------------------
AEMO_URL = "https://visualisations.aemo.com.au/aemo/apps/api/report/ELEC_NEM_SUMMARY"
REGION = "QLD1"
CSV_FILE = "qld_decisions.csv"
POLL_SECONDS = 300   # 5 minutes


def fetch_qld():
    """
    Fetches the current QLD reading from AEMO.
    Returns (settlement_date, price, demand) or raises on failure.
    """
    response = requests.get(AEMO_URL, timeout=15)
    response.raise_for_status()
    data = response.json()

    # The endpoint returns a list under "ELEC_NEM_SUMMARY"; grab the QLD row.
    for row in data["ELEC_NEM_SUMMARY"]:
        if row["REGIONID"] == REGION:
            settlement = row["SETTLEMENTDATE"]      # dispatch-interval label
            price = float(row["PRICE"])             # $/MWh
            demand = float(row["TOTALDEMAND"])      # MW
            return settlement, price, demand

    raise ValueError(f"No {REGION} row found in AEMO response.")


def append_row(settlement, price, demand, result):
    """Appends one reading (with its decision) to the CSV, writing a header once."""
    file_exists = os.path.isfile(CSV_FILE)

    with open(CSV_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "wall_clock", "settlement_date", "price_mwh",
                "demand_mw", "action", "score", "reason",
            ])
        writer.writerow([
            datetime.now().isoformat(timespec="seconds"),
            settlement,
            price,
            demand,
            result["action"],
            result["score"],
            result["reason"],
        ])


def run():
    print("Solar Spill scheduler running. Ctrl+C to stop.\n")
    while True:
        try:
            settlement, price, demand = fetch_qld()
            result = decide(price, demand)

            # Print a clean one-line status.
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"${price:>6.0f}/MWh  {demand:>6.0f} MW  ->  "
                f"{result['action']:<7} (health {result['score']}/10)  "
                f"{result['reason']}"
            )

            append_row(settlement, price, demand, result)

        except Exception as e:
            # Same philosophy as logger.py: survive network dropouts, keep going.
            print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                  f"skipped this interval — {type(e).__name__}: {e}")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()
