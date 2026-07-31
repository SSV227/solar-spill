"""
server.py — Solar Spill Phase 4
Serves the live charge/wait decision as JSON for the ESP32 to consume.

AEMO updates every 5 minutes; the ESP32 polls every 5 seconds. A cache
sits between them so we make one upstream call per settlement interval
rather than ~60 redundant ones.
"""

import time
from flask import Flask, jsonify

from price_check import get_qld_price
from decision import decide

app = Flask(__name__)

CACHE_SECONDS = 120
_cache = {"fetched_at": 0.0, "payload": None}


def build_payload():
    """Fetch from AEMO, run the decision engine, shape it for the client."""
    settlement, price, demand = get_qld_price()
    result = decide(price, demand)

    return {
        "charge": result["action"] == "CHARGE",
        "action": result["action"],
        "health": result["score"],
        "reason": result["reason"],
        "price": round(price, 2),
        "demand": round(demand),
        "settlement": settlement,
    }


def get_payload():
    """Return a cached payload, refreshing only when it has gone stale."""
    age = time.time() - _cache["fetched_at"]

    if _cache["payload"] is None or age > CACHE_SECONDS:
        try:
            _cache["payload"] = build_payload()
            _cache["fetched_at"] = time.time()
            print(f"[cache] refreshed: {_cache['payload']}")
        except Exception as exc:
            # AEMO unreachable. Serve stale data if we have it, rather than
            # failing the request — a slightly old price beats no price.
            print(f"[cache] AEMO fetch failed: {exc}")
            if _cache["payload"] is None:
                raise

    return _cache["payload"]


@app.route("/decision")
def decision():
    try:
        return jsonify(get_payload())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 503


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)