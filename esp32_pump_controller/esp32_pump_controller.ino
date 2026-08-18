#include <HTTPClient.h>
#include <Preferences.h>
#include <WiFi.h>
#include <driver/gpio.h>

#include "secrets.h"

// The Atlas USB connection enumerates the board's CH340 UART. Route the
// controller protocol explicitly through UART0 instead of USB CDC.
#define Serial Serial0

constexpr int PUMP_PIN = 42;
constexpr bool DEFAULT_PUMP_ACTIVE_HIGH = true;
constexpr unsigned long POLL_INTERVAL_MS = 1000;
constexpr unsigned long REPORT_INTERVAL_MS = 5000;
constexpr unsigned long AUTO_SENSOR_POLL_MS = 5000;
// Match the dashboard's default manual run limit. A bounded limit still
// protects the pump if the browser or network disappears.
constexpr unsigned long DEFAULT_MAX_RUN_MS = 180000;
constexpr float DEFAULT_ON_THRESHOLD = 30.0F;
constexpr float DEFAULT_OFF_THRESHOLD = 55.0F;
constexpr unsigned long DEFAULT_MIN_RUN_MS = 15000;
// The Atlas USB/UART link is the primary control path. Keep Wi-Fi code only
// as an optional legacy fallback, but never let it delay serial control.
constexpr bool WIRED_ONLY = true;

const char *DEVICE_ID = "esp32s3-pump-ac-a7-04-15-b2-4c";

bool pumpOn = false;
bool pumpActiveHigh = DEFAULT_PUMP_ACTIVE_HIGH;
String controlMode = "manual";
unsigned long startedAt = 0;
unsigned long lastPollAt = 0;
unsigned long lastReportAt = 0;
unsigned long lastServerOkAt = 0;
unsigned long lastWifiAttemptAt = 0;
unsigned long wifiDisconnectedAt = 0;
unsigned long maxRunMs = DEFAULT_MAX_RUN_MS;
unsigned long minRunMs = DEFAULT_MIN_RUN_MS;
unsigned long lastAutoSensorPollAt = 0;
float onThreshold = DEFAULT_ON_THRESHOLD;
float offThreshold = DEFAULT_OFF_THRESHOLD;
bool autoRulesConfigured = false;
float latestSoilMoisture = -1.0F;
String lastError;
String lastCommandId;
Preferences preferences;
String serialLine;

String endpoint(const char *suffix) {
  return String(SERVER_URL) + "/api/devices/" + DEVICE_ID + suffix;
}

void setPump(bool enabled, const char *reason) {
  digitalWrite(PUMP_PIN, (enabled == pumpActiveHigh) ? HIGH : LOW);
  pumpOn = enabled;
  if (enabled) {
    startedAt = millis();
    lastError = "";
  } else {
    startedAt = 0;
    if (reason && reason[0]) lastError = reason;
  }
  Serial.printf("Pump %s at %lu ms (max=%lu), reason=%s\\n", enabled ? "ON" : "OFF", millis(), maxRunMs, reason ? reason : "");
}

void saveValveSettings() {
  preferences.begin("zhirun-valve", false);
  preferences.putFloat("on_th", onThreshold);
  preferences.putFloat("off_th", offThreshold);
  preferences.putULong("min_run", minRunMs);
  preferences.putULong("max_run", maxRunMs);
  preferences.putBool("auto_ready", autoRulesConfigured);
  preferences.putString("mode", controlMode);
  preferences.end();
}

void loadValveSettings() {
  // On a freshly erased device the namespace does not exist yet. Open it
  // read-write once so Preferences creates it instead of failing at boot.
  preferences.begin("zhirun-valve", false);
  onThreshold = preferences.getFloat("on_th", DEFAULT_ON_THRESHOLD);
  offThreshold = preferences.getFloat("off_th", DEFAULT_OFF_THRESHOLD);
  minRunMs = preferences.getULong("min_run", DEFAULT_MIN_RUN_MS);
  maxRunMs = preferences.getULong("max_run", DEFAULT_MAX_RUN_MS);
  autoRulesConfigured = preferences.getBool("auto_ready", false);
  controlMode = preferences.getString("mode", "manual");
  preferences.end();
  if (onThreshold < 0 || offThreshold > 100 || onThreshold >= offThreshold || minRunMs >= maxRunMs) {
    onThreshold = DEFAULT_ON_THRESHOLD;
    offThreshold = DEFAULT_OFF_THRESHOLD;
    minRunMs = DEFAULT_MIN_RUN_MS;
    maxRunMs = DEFAULT_MAX_RUN_MS;
    autoRulesConfigured = false;
  }
  if (controlMode != "manual" && controlMode != "auto") controlMode = "manual";
}

String jsonEscape(const String &value) {
  String escaped;
  for (size_t i = 0; i < value.length(); ++i) {
    const char c = value[i];
    if (c == '\\' || c == '"') escaped += '\\';
    escaped += c;
  }
  return escaped;
}

bool postJson(const String &url, const String &body) {
  HTTPClient http;
  http.setConnectTimeout(4000);
  http.setTimeout(5000);
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  const int status = http.POST(body);
  http.end();
  if (status >= 200 && status < 300) {
    lastServerOkAt = millis();
    return true;
  }
  Serial.printf("POST failed: %d\\n", status);
  return false;
}

void reportState() {
  if (!WiFi.isConnected()) return;
  const String ssid = WiFi.isConnected() ? WiFi.SSID() : "";
  const String ip = WiFi.isConnected() ? WiFi.localIP().toString() : "";
  const unsigned long runSeconds = pumpOn ? (millis() - startedAt) / 1000UL : 0;
  const String state = String("{\"valveOn\":") + (pumpOn ? "true" : "false") +
      ",\"manualOpen\":" + (pumpOn ? "true" : "false") +
      ",\"gpio42High\":" + (digitalRead(PUMP_PIN) == HIGH ? "true" : "false") +
      ",\"gpio42Level\":" + String(digitalRead(PUMP_PIN)) +
      ",\"activeHigh\":" + (pumpActiveHigh ? "true" : "false") +
      ",\"mode\":\"" + controlMode + "\",\"runSeconds\":" + runSeconds +
      ",\"onTh\":" + String(onThreshold, 1) +
      ",\"offTh\":" + String(offThreshold, 1) +
      ",\"minRunS\":" + String(minRunMs / 1000UL) +
      ",\"maxRunSeconds\":" + (maxRunMs / 1000UL) +
      ",\"maxRunS\":" + String(maxRunMs / 1000UL) +
      ",\"autoRulesConfigured\":" + (autoRulesConfigured ? "true" : "false") +
      ",\"wifiConnected\":" + (WiFi.isConnected() ? "true" : "false") +
      ",\"wifiSsid\":\"" + jsonEscape(ssid) + "\",\"ip\":\"" + jsonEscape(ip) +
      "\",\"error\":\"" + jsonEscape(lastError) +
      "\",\"lastCommandId\":\"" + jsonEscape(lastCommandId) + "\"}";
  postJson(endpoint("/valve/result"), String("{\"token\":\"") + PUSH_TOKEN + "\",\"state\":" + state + "}");
}

void reportSerialState() {
  const unsigned long runSeconds = pumpOn ? (millis() - startedAt) / 1000UL : 0;
  Serial.println(String("STATE {\"valveOn\":") + (pumpOn ? "true" : "false") +
      ",\"manualOpen\":" + (pumpOn ? "true" : "false") +
      ",\"gpio42High\":" + (digitalRead(PUMP_PIN) == HIGH ? "true" : "false") +
      ",\"gpio42Level\":" + String(digitalRead(PUMP_PIN)) +
      ",\"activeHigh\":" + (pumpActiveHigh ? "true" : "false") +
      ",\"mode\":\"" + controlMode + "\",\"runSeconds\":" + runSeconds +
      ",\"onTh\":" + String(onThreshold, 1) + ",\"offTh\":" + String(offThreshold, 1) +
      ",\"minRunS\":" + String(minRunMs / 1000UL) + ",\"maxRunS\":" + String(maxRunMs / 1000UL) +
      ",\"autoRulesConfigured\":" + (autoRulesConfigured ? "true" : "false") +
      ",\"soilMoist\":" + String(latestSoilMoisture, 1) + ",\"error\":\"" + jsonEscape(lastError) + "\"}");
}

void heartbeat() {
  const String ip = WiFi.isConnected() ? WiFi.localIP().toString() : "";
  const String payload = String("{\"networkConnected\":") + (WiFi.isConnected() ? "true" : "false") +
      ",\"networkType\":\"wifi\",\"networkInterface\":\"wlan0\",\"networkIp\":\"" +
      jsonEscape(ip) + "\",\"valveOn\":" + (pumpOn ? "true" : "false") + "}";
  const String body = String("{\"token\":\"") + PUSH_TOKEN + "\",\"device_id\":\"" + DEVICE_ID +
      "\",\"device_name\":\"ESP32-S3 水泵控制器\",\"model\":\"ESP32-S3 N16R8\",\"firmware_version\":\"1.0.0\",\"ip\":\"" +
      jsonEscape(ip) + "\",\"network_type\":\"wifi\",\"capabilities\":[\"valve_control\",\"wifi\"],\"data_source\":\"device\",\"payload\":" + payload + "}";
  postJson(String(SERVER_URL) + "/push", body);
}

long jsonInteger(const String &json, const char *key, long fallback) {
  const String marker = String("\"") + key + "\":";
  const int start = json.indexOf(marker);
  if (start < 0) return fallback;
  int end = start + marker.length();
  while (end < (int)json.length() && (json[end] == ' ' || json[end] == '"')) ++end;
  int finish = end;
  while (finish < (int)json.length() && isDigit(json[finish])) ++finish;
  return finish > end ? json.substring(end, finish).toInt() : fallback;
}

float jsonFloat(const String &json, const char *key, float fallback) {
  const String marker = String("\"") + key + "\":";
  const int start = json.indexOf(marker);
  if (start < 0) return fallback;
  int valueStart = start + marker.length();
  while (valueStart < (int)json.length() && json[valueStart] == ' ') ++valueStart;
  int valueEnd = valueStart;
  if (valueEnd < (int)json.length() && json[valueEnd] == '-') ++valueEnd;
  while (valueEnd < (int)json.length() && (isDigit(json[valueEnd]) || json[valueEnd] == '.')) ++valueEnd;
  return valueEnd > valueStart ? json.substring(valueStart, valueEnd).toFloat() : fallback;
}

bool jsonBoolean(const String &json, const char *key, bool fallback) {
  const String marker = String("\"") + key + "\":";
  const int start = json.indexOf(marker);
  if (start < 0) return fallback;
  const int valueStart = start + marker.length();
  if (json.startsWith("true", valueStart) || json.startsWith("1", valueStart)) return true;
  if (json.startsWith("false", valueStart) || json.startsWith("0", valueStart)) return false;
  return fallback;
}

void handleCommand(const String &json) {
  Serial.printf("Command: %s\\n", json.c_str());
  const int commandStart = json.indexOf("\"command\":{");
  if (commandStart < 0) return;

  const int idStart = json.indexOf("\"id\":\"", commandStart);
  if (idStart >= 0) {
    const int valueStart = idStart + 6;
    const int valueEnd = json.indexOf('"', valueStart);
    if (valueEnd > valueStart) lastCommandId = json.substring(valueStart, valueEnd);
  }

  const bool isManual = json.indexOf("\"action\":\"manual\"", commandStart) >= 0;
  if (isManual) {
    controlMode = "manual";
    if (json.indexOf("\"manual_action\":\"open\"", commandStart) >= 0) {
      setPump(true, "");
    } else if (json.indexOf("\"manual_action\":\"close\"", commandStart) >= 0) {
      setPump(false, "manual_close");
    } else {
      lastError = "bad_manual_action";
    }
    saveValveSettings();
  }
  if (json.indexOf("\"action\":\"mode\"", commandStart) >= 0) {
    if (json.indexOf("\"mode\":\"manual\"", commandStart) >= 0) {
      controlMode = "manual";
      // Leaving automatic control must never leave the pump running.
      if (pumpOn) setPump(false, "mode_manual");
    } else if (json.indexOf("\"mode\":\"auto\"", commandStart) >= 0) {
      controlMode = "auto";
      if (pumpOn) setPump(false, "mode_auto");
    } else {
      lastError = "bad_mode";
    }
    saveValveSettings();
  }
  if (json.indexOf("\"action\":\"config\"", commandStart) >= 0) {
    const bool hasThresholds = json.indexOf("\"on_th\":", commandStart) >= 0 ||
        json.indexOf("\"off_th\":", commandStart) >= 0 ||
        json.indexOf("\"min_run_s\":", commandStart) >= 0;
    const float requestedOn = jsonFloat(json, "on_th", onThreshold);
    const float requestedOff = jsonFloat(json, "off_th", offThreshold);
    const long requestedMin = jsonInteger(json, "min_run_s", minRunMs / 1000UL);
    const long seconds = jsonInteger(json, "max_run_s", maxRunMs / 1000UL);
    if (requestedOn < 0 || requestedOff > 100 || requestedOn >= requestedOff ||
        requestedMin < 0 || requestedMin >= seconds) {
      lastError = "invalid_config";
    } else {
      onThreshold = requestedOn;
      offThreshold = requestedOff;
      minRunMs = constrain(requestedMin, 0L, 300L) * 1000UL;
      maxRunMs = constrain(seconds, 1L, 300L) * 1000UL;
      if (hasThresholds) autoRulesConfigured = true;
      lastError = "";
      saveValveSettings();
    }
    const bool requestedActiveHigh = jsonBoolean(json, "active_high", pumpActiveHigh);
    if (requestedActiveHigh != pumpActiveHigh) {
      if (pumpOn) setPump(false, "polarity_changed");
      pumpActiveHigh = requestedActiveHigh;
      setPump(false, "polarity_changed");
    }
  }
  if (json.indexOf("\"action\":\"sensor\"", commandStart) >= 0) {
    const float soil = jsonFloat(json, "soil_moist", -1.0F);
    if (soil >= 0.0F && soil <= 100.0F) latestSoilMoisture = soil;
  }
  reportState();
}

void pollSerialCommands() {
  while (Serial.available()) {
    const char c = static_cast<char>(Serial.read());
    if (c == '\r') continue;
    if (c != '\n') {
      if (serialLine.length() < 768) serialLine += c;
      else serialLine = "";
      continue;
    }
    if (serialLine.indexOf("\"command\":{") >= 0) {
      handleCommand(serialLine);
    } else if (serialLine == "STATUS") {
      reportSerialState();
    }
    serialLine = "";
  }
}

void updateAutomaticControl(unsigned long now) {
  if (controlMode != "auto" || !autoRulesConfigured || now - lastAutoSensorPollAt < AUTO_SENSOR_POLL_MS) return;
  lastAutoSensorPollAt = now;

  if (latestSoilMoisture >= 0.0F && latestSoilMoisture <= 100.0F) {
    const float soil = latestSoilMoisture;
    if (!pumpOn && soil < onThreshold) setPump(true, "");
    else if (pumpOn && now - startedAt >= minRunMs && soil >= offThreshold) setPump(false, "auto_moisture_reached");
    return;
  }
  if (!WiFi.isConnected()) {
    lastError = "auto_soil_unavailable";
    return;
  }
  HTTPClient http;
  http.setConnectTimeout(3000);
  http.setTimeout(3500);
  http.begin(String(SERVER_URL) + "/data");
  const int status = http.GET();
  const String response = status >= 200 && status < 300 ? http.getString() : "";
  http.end();
  const float soil = jsonFloat(response, "soilMoist", -1.0F);
  // A zero moisture value is a valid, very dry reading. Only a missing
  // value (parsed as -1) or an out-of-range value blocks automatic control.
  if (soil < 0.0F || soil > 100.0F) {
    lastError = "auto_soil_unavailable";
    return;
  }
  if (!pumpOn && soil < onThreshold) {
    setPump(true, "");
    reportState();
  } else if (pumpOn && now - startedAt >= minRunMs && soil >= offThreshold) {
    setPump(false, "auto_moisture_reached");
    reportState();
  }
}

void pollCommand() {
  HTTPClient http;
  http.setConnectTimeout(4000);
  http.setTimeout(5000);
  http.begin(endpoint("/valve/commands/next?token=") + PUSH_TOKEN);
  const int status = http.GET();
  if (status >= 200 && status < 300) {
    lastServerOkAt = millis();
    const String response = http.getString();
    Serial.printf("Poll OK: %s\\n", response.c_str());
    handleCommand(response);
  } else {
    Serial.printf("Poll failed: %d\\n", status);
  }
  http.end();
}

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  const int networks = WiFi.scanNetworks(false, true);
  Serial.printf("Wi-Fi scan count: %d\\n", networks);
  for (int i = 0; i < networks; ++i) {
    Serial.printf("  %s RSSI=%d CH=%d\\n", WiFi.SSID(i).c_str(), WiFi.RSSI(i), WiFi.channel(i));
  }
  WiFi.scanDelete();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  lastWifiAttemptAt = millis();
  Serial.printf("Connecting to Wi-Fi: %s\\n", WIFI_SSID);
}

void setup() {
  Serial.begin(115200);
  delay(200);
  pinMode(PUMP_PIN, OUTPUT);
  gpio_set_drive_capability(static_cast<gpio_num_t>(PUMP_PIN), GPIO_DRIVE_CAP_3);
  loadValveSettings();
  setPump(false, "boot_safe_off");
  Serial.println("Pump safe-off; starting controller");
  if (!WIRED_ONLY) connectWifi();
}

void loop() {
  const unsigned long now = millis();
  pollSerialCommands();
  updateAutomaticControl(now);
  // Manual mode remains on until an explicit close command. The maximum
  // runtime is an automatic-mode safety limit only.
  if (controlMode == "auto" && pumpOn && millis() - startedAt >= maxRunMs) {
    setPump(false, "max_runtime_reached");
  }
  if (WIRED_ONLY) {
    delay(20);
    return;
  }
  if (!WiFi.isConnected()) {
    if (!wifiDisconnectedAt) wifiDisconnectedAt = now;
    static unsigned long lastWifiLogAt = 0;
    if (now - lastWifiLogAt >= 5000) {
      lastWifiLogAt = now;
      Serial.printf("Wi-Fi status: %d\\n", WiFi.status());
    }
    if (now - lastWifiAttemptAt >= 10000) connectWifi();
    delay(250);
    return;
  }
  wifiDisconnectedAt = 0;
  static bool loggedConnected = false;
  if (!loggedConnected) {
    loggedConnected = true;
    Serial.printf("Wi-Fi connected: %s\\n", WiFi.localIP().toString().c_str());
  }
  if (now - lastPollAt >= POLL_INTERVAL_MS) {
    lastPollAt = now;
    pollCommand();
  }
  // pollCommand() may turn the pump on after `now` was sampled above.  Read
  // the clock again so `startedAt` cannot be newer than the comparison time.
  if (controlMode == "auto" && pumpOn && millis() - startedAt >= maxRunMs) {
    setPump(false, "max_runtime_reached");
  }
  if (now - lastReportAt >= REPORT_INTERVAL_MS) {
    lastReportAt = now;
    heartbeat();
    reportState();
  }
  delay(20);
}
