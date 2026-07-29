#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "secrets.h"

const char* WIFI_SSID     = WIFI_SSID_SECRET;
const char* WIFI_PASSWORD = WIFI_PASSWORD_SECRET;
const char* SERVER_URL    = "http://192.168.0.229:5001/decision";

#define LED_PIN 2

void setup() {
  Serial.begin(115200);
  delay(2000);

  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("Connecting");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("Connected. My IP: ");
  Serial.println(WiFi.localIP());
}

void loop() {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(SERVER_URL);
    int code = http.GET();

    if (code == 200) {
      String payload = http.getString();

      JsonDocument doc;
      DeserializationError err = deserializeJson(doc, payload);

      if (err) {
        Serial.print("JSON parse failed: ");
        Serial.println(err.c_str());
        digitalWrite(LED_PIN, LOW);
      } else {
        bool  charge = doc["charge"];
        int   health = doc["health"];
        float price  = doc["price"];

        Serial.print("charge=");
        Serial.print(charge ? "YES" : "NO");
        Serial.print("  health=");
        Serial.print(health);
        Serial.print("  price=$");
        Serial.println(price);

        digitalWrite(LED_PIN, charge ? HIGH : LOW);
      }
    } else {
      Serial.print("HTTP error: ");
      Serial.println(code);
      digitalWrite(LED_PIN, LOW);
    }

    http.end();
  }

  delay(5000);
}