// solarspill_suburb.ino
// Ten-house demonstrator. Polls /suburb on the Mac and lights one LED per
// charging house. Onboard RGB LED (GPIO 48) is the transformer:
//   green = within capacity, red = overloaded.
// Press the BOOT button to switch between smart and coordinated.

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "secrets.h"

const char* WIFI_SSID     = WIFI_SSID_SECRET;
const char* WIFI_PASSWORD = WIFI_PASSWORD_SECRET;
const char* SERVER_BASE   = "http://192.168.0.229:5001";  // your Mac's IP

const int NUM_HOUSES = 10;
const int HOUSE_PINS[NUM_HOUSES] = {1, 2, 4, 5, 6, 7, 15, 16, 17, 18};
const int RGB_PIN    = 48;
const int BUTTON_PIN = 0;   // onboard BOOT button, reads LOW when pressed

const unsigned long POLL_MS = 250;
unsigned long lastPoll = 0;
bool lastButton = HIGH;

void setTransformer(bool overloaded) {
  if (overloaded) neopixelWrite(RGB_PIN, 40, 0, 0);   // red
  else            neopixelWrite(RGB_PIN, 0, 40, 0);   // green
}

void allOff() {
  for (int i = 0; i < NUM_HOUSES; i++) digitalWrite(HOUSE_PINS[i], LOW);
}

bool httpGet(const String& path, String& body) {
  HTTPClient http;
  http.setTimeout(1000);
  http.begin(String(SERVER_BASE) + path);
  int code = http.GET();
  if (code == 200) body = http.getString();
  http.end();
  return code == 200;
}

void setup() {
  Serial.begin(115200);
  delay(2000);

  for (int i = 0; i < NUM_HOUSES; i++) {
    pinMode(HOUSE_PINS[i], OUTPUT);
    digitalWrite(HOUSE_PINS[i], LOW);
  }
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  neopixelWrite(RGB_PIN, 0, 0, 40);   // blue while connecting

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.print("\nConnected. My IP: ");
  Serial.println(WiFi.localIP());
}

void loop() {
  // Button: act once per press, not continuously while held.
  bool button = digitalRead(BUTTON_PIN);
  if (lastButton == HIGH && button == LOW) {
    String ignored;
    httpGet("/suburb/toggle", ignored);
    Serial.println("Mode toggled");
    delay(200);  // debounce
  }
  lastButton = button;

  if (millis() - lastPoll < POLL_MS) return;
  lastPoll = millis();

  if (WiFi.status() != WL_CONNECTED) {
    allOff();
    neopixelWrite(RGB_PIN, 0, 0, 40);
    return;
  }

  String body;
  if (!httpGet("/suburb", body)) {
    allOff();
    neopixelWrite(RGB_PIN, 0, 0, 40);   // blue = can't reach server
    return;
  }

  JsonDocument doc;
  if (deserializeJson(doc, body)) return;

  JsonArray houses = doc["houses"];
  for (int i = 0; i < NUM_HOUSES; i++) {
    digitalWrite(HOUSE_PINS[i], houses[i].as<bool>() ? HIGH : LOW);
  }
  setTransformer(doc["overloaded"]);

  Serial.printf("%s  %s  $%.2f  %d/%d charging%s\n",
                doc["mode"].as<const char*>(),
                doc["sim_time"].as<const char*>(),
                doc["price"].as<float>(),
                doc["charging_now"].as<int>(),
                doc["capacity"].as<int>(),
                doc["overloaded"].as<bool>() ? "  OVERLOAD" : "");
}
