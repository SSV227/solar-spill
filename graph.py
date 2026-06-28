import pandas as pd
import matplotlib.pyplot as plt

CSV_FILE = "qld_prices.csv"

df = pd.read_csv(CSV_FILE, names=["settlement", "price", "demand"])
df["settlement"] = pd.to_datetime(df["settlement"])
df = df.sort_values("settlement")

# --- Keep only Saturday 27 June 2026 ---
df = df[df["settlement"].dt.date == pd.to_datetime("2026-06-27").date()]

# --- Break the line where there's a gap bigger than ~6 minutes ---
# Insert a blank row wherever consecutive readings are more than 6 min apart,
# so matplotlib lifts its pen instead of drawing a fake straight line.
gap = df["settlement"].diff() > pd.Timedelta(minutes=6)
df.loc[gap, ["price", "demand"]] = None

fig, ax1 = plt.subplots(figsize=(12, 6))

ax1.plot(df["settlement"], df["price"], color="tab:blue", marker="o", markersize=3, linewidth=1)
ax1.set_xlabel("Time (AEST)")
ax1.set_ylabel("Price ($/MWh)", color="tab:blue")
ax1.tick_params(axis="y", labelcolor="tab:blue")

ax2 = ax1.twinx()
ax2.plot(df["settlement"], df["demand"], color="tab:red", marker="o", markersize=3, linewidth=1)
ax2.set_ylabel("Demand (MW)", color="tab:red")
ax2.tick_params(axis="y", labelcolor="tab:red")

plt.title("Queensland Grid — Price & Demand, Saturday 27 June 2026")
fig.tight_layout()
fig.text(0.5, 0.01, "Gaps reflect network dropouts during logging — no data interpolated.",
         ha="center", fontsize=8, style="italic", color="gray")
plt.savefig("qld_day_graph.png", dpi=150)
plt.show()