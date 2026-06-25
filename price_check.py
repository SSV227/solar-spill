import requests

URL = "https://visualisations.aemo.com.au/aemo/apps/api/report/ELEC_NEM_SUMMARY"

def get_qld_price():
    response = requests.get(URL, timeout=10)
    response.raise_for_status()
    rows = response.json()["ELEC_NEM_SUMMARY"]
    qld = next(r for r in rows if r["REGIONID"] == "QLD1")
    return qld["SETTLEMENTDATE"], qld["PRICE"], qld["TOTALDEMAND"]

time, price, demand = get_qld_price()
print(f"[{time}]  QLD price: ${price:.2f}/MWh  ({price/10:.2f} c/kWh)  |  demand: {demand:.0f} MW")