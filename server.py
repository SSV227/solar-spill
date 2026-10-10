"""
server.py - Solar Spill Phase 4
Serves two things for the ESP32:

  /decision        Live charge/wait call from AEMO data (single-LED demo).
  /suburb          Ten-house demonstrator replaying a real QLD night.
  /suburb/toggle   Switch between smart and coordinated, restart the night.
  /suburb/reset    Restart the night in the current mode.

AEMO updates every 5 minutes; the board polls far more often. A cache sits
between them so we make one upstream call per settlement interval.
"""

import time
from flask import Flask, jsonify

from price_check import get_qld_price
from decision import decide
from suburb_demo import SuburbDemo

app = Flask(__name__)

CACHE_SECONDS = 120
_cache = {"fetched_at": 0.0, "payload": None}

demo = SuburbDemo()


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
            # Serve stale data if we have it rather than failing the request.
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


@app.route("/suburb")
def suburb():
    return jsonify(demo.state())


@app.route("/suburb/toggle")
def suburb_toggle():
    mode = demo.toggle()
    print(f"[suburb] mode -> {mode}")
    return jsonify(demo.state())


@app.route("/suburb/reset")
def suburb_reset():
    demo.reset()
    return jsonify(demo.state())


if __name__ == "__main__":
    # use_reloader=False keeps a single demo clock; with the reloader on,
    # Flask runs two processes and the toggle can land on the wrong one.
    app.run(host="0.0.0.0", port=5001, debug=True, use_reloader=False)
