# Solar Spill

A Queensland-specific EV smart charging scheduler that shifts EV charging
into the cheapest, lowest-demand, highest-solar windows on the Queensland grid.

Unlike national tools that optimise one household against a single price feed,
Solar Spill reads live Queensland grid data every 5 minutes and is aware of
suburb-level coordinated demand — staggering charging to avoid creating a new
peak rather than just relocating the old one.

## Status

Phase 1 — live grid data pipeline.

- `price_check.py` — fetches the current QLD spot price and demand from AEMO.
- `logger.py` — polls every 5 minutes and logs each reading to CSV.

## Data source

AEMO `ELEC_NEM_SUMMARY` feed — live 5-minute dispatch price and demand for
all NEM regions. Solar Spill filters to the QLD1 region.

## Running it
python3 -m venv venv

source venv/bin/activate

pip install requests

python logger.py
## Roadmap

1. Live grid data pipeline (current)
2. Decision logic — rule-based charge/wait + grid health score
3. Suburb simulation — staggered vs naive charging, peak-reduction result
4. Physical demo (ESP32) + web dashboard
5. Write-up

## Tech

Python, requests. Planned: pandas, matplotlib, Flask/FastAPI, SQLite, ESP32.