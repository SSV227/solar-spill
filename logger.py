import requests
import csv
import time
from datetime import datetime

URL = "https://visualisations.aemo.com.au/aemo/apps/api/report/ELEC_NEM_SUMMARY"
CSV_FILE = "qld_prices.csv"

def get_qld_price():
    response = requests.get(URL, timeout=10)
    response.raise_for_status()
    rows = response.json()["ELEC_NEM_SUMMARY"]
    qld = next(r for r in rows if r["REGIONID"] == "QLD1")
    return qld["SETTLEMENTDATE"], qld["PRICE"], qld["TOTALDEMAND"]

def save_row(settlement, price, demand):
    with open(CSV_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([settlement, price, demand])

print("Solar Spill logger running — Ctrl+C to stop\n")
while True:
    try:
        settlement, price, demand = get_qld_price()
        now = datetime.now().strftime("%H:%M:%S")
        print(f"{now}  |  {settlement}  |  ${price:7.2f}/MWh  |  {demand:.0f} MW")
        save_row(settlement, price, demand)
    except Exception as e:
        print(f"  fetch failed: {e}  — retrying in 5 min")
    time.sleep(300)   # 5 minutes