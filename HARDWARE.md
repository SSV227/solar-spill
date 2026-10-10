# Hardware notes

## Board

Freenove ESP32-S3 (8 MB PSRAM), programmed with Arduino IDE 2.x and the Espressif `esp32` board package (3.3.x).

| Setting | Value |
|---|---|
| Board | ESP32S3 Dev Module |
| USB CDC On Boot | Enabled |
| Baud | 115200 |
| Library | ArduinoJson (Benoit Blanchon), via Library Manager |

Use the USB-C port that enumerates as `/dev/cu.usbmodem...` on macOS. On this board the other port produced garbage on the serial monitor with CDC enabled. The port number changes on replug; any `usbmodem` entry is the board.

## Wi-Fi

The ESP32 only supports 2.4 GHz. Credentials live in `secrets.h` next to the sketch (gitignored). Copy `secrets.h.example` and fill it in.

The board and the Mac running `server.py` must be on the same network. Both addresses come from DHCP and can change: if the board reports HTTP errors, check the Mac's current IP first and update `SERVER_URL` in the sketch.

**Debugging a failed join:** plain `WiFi.begin()` just loops forever. Register `WiFi.onEvent()` and print `info.wifi_sta_disconnected.reason`. Reason 15 is an authentication failure: usually a wrong password, occasionally a signal too weak to finish the handshake.

## LED wiring

Each LED: `GPIO -> 220 ohm resistor -> LED long leg (anode)`, `LED short leg (cathode) -> shared ground rail -> GND`.

Single-LED demo: GPIO 2.

Ten-house demonstrator, left to right:

| House | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|---|
| GPIO | 1 | 2 | 4 | 5 | 6 | 7 | 15 | 16 | 17 | 18 |

Physical order verified with `esp32/led_sweep_test`. Avoid GPIO 0, 3, 19, 20, 26 to 37, 43 to 46 and 48 for external LEDs (boot strapping, USB, flash/PSRAM, UART, onboard RGB).

Blue LEDs have a forward voltage of about 3.0 to 3.2 V, close to the 3.3 V supply. They light at 220 ohm but brightness can vary slightly between parts. A dark LED is far more likely to be in backwards than faulty.

## Running the demo

```bash
cd solar-spill
source venv/bin/activate
python server.py
```

Check `http://<mac-ip>:5001/decision` loads in a browser, then power the board. Stop the server with Ctrl+C. Closing the terminal window can leave it running; if you then see "port 5001 in use", run `lsof -ti :5001 | xargs kill -9`.
