from flask import Flask, jsonify

app = Flask(__name__)


@app.route("/decision")
def decision():
    # Hardcoded for now. Phase 4 Step 4 wires this to the real engine.
    return jsonify({
        "charge": True,
        "health": 7,
        "price": 42.50
    })


if __name__ == "__main__":
    # host="0.0.0.0" makes the server visible to other devices on the network.
    # Without it Flask only listens on localhost and the ESP32 can't reach it.
    app.run(host="0.0.0.0", port=5001, debug=True)