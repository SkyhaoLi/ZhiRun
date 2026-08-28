#include <Preferences.h>
#include <driver/gpio.h>

// RK3506B communicates with the ESP32-S3 through the CH341 UART bridge.
#define Serial Serial0

// Relay inputs are high-level triggered. N/P/K map to IN1/IN2/IN3.
constexpr int PUMP_COUNT = 3;
constexpr int PUMP_PINS[PUMP_COUNT] = {4, 5, 6};
constexpr const char *PUMP_NAMES[PUMP_COUNT] = {"n", "p", "k"};
constexpr int RAIN_PIN = 18;
constexpr float RAIN_MM_PER_TIP = 0.3F;
constexpr uint32_t RAIN_DEBOUNCE_US = 50000;
constexpr unsigned long MAX_TEST_RUN_MS = 180000;

volatile uint32_t rainTips = 0;
volatile uint32_t lastRainPulseUs = 0;
bool pumpOn[PUMP_COUNT] = {false, false, false};
unsigned long pumpStartedAt[PUMP_COUNT] = {0, 0, 0};
String controlMode = "manual";
String lastError = "boot_safe_off";
String lastCommandId;
String serialLine;
Preferences preferences;

void IRAM_ATTR onRainTip() {
  const uint32_t now = micros();
  if (now - lastRainPulseUs >= RAIN_DEBOUNCE_US) {
    ++rainTips;
    lastRainPulseUs = now;
  }
}

uint32_t rainTipSnapshot() {
  noInterrupts();
  const uint32_t value = rainTips;
  interrupts();
  return value;
}

String jsonEscape(const String &value) {
  String escaped;
  for (size_t index = 0; index < value.length(); ++index) {
    const char character = value[index];
    if (character == '\\' || character == '"') escaped += '\\';
    escaped += character;
  }
  return escaped;
}

String jsonString(const String &json, const char *key, const String &fallback = "") {
  const String marker = String("\"") + key + "\":\"";
  const int markerAt = json.indexOf(marker);
  if (markerAt < 0) return fallback;
  const int start = markerAt + marker.length();
  const int end = json.indexOf('"', start);
  return end > start ? json.substring(start, end) : fallback;
}

int pumpIndex(const String &name) {
  for (int index = 0; index < PUMP_COUNT; ++index) {
    if (name.equalsIgnoreCase(PUMP_NAMES[index])) return index;
  }
  return -1;
}

bool anyPumpOn() {
  for (int index = 0; index < PUMP_COUNT; ++index) {
    if (pumpOn[index]) return true;
  }
  return false;
}

void setPump(int index, bool enabled, const char *reason) {
  if (index < 0 || index >= PUMP_COUNT) return;
  digitalWrite(PUMP_PINS[index], enabled ? HIGH : LOW);
  pumpOn[index] = enabled;
  pumpStartedAt[index] = enabled ? millis() : 0;
  if (enabled) {
    lastError = "";
  } else if (reason && reason[0]) {
    lastError = reason;
  }
}

void stopAll(const char *reason) {
  for (int index = 0; index < PUMP_COUNT; ++index) setPump(index, false, reason);
}

unsigned long runSeconds(int index) {
  return pumpOn[index] ? (millis() - pumpStartedAt[index]) / 1000UL : 0;
}

void saveMode() {
  preferences.begin("zhirun-valve", false);
  preferences.putString("mode", "manual");
  preferences.end();
}

void reportSerialState() {
  const uint32_t tips = rainTipSnapshot();
  Serial.println(String("STATE {\"controllerSchema\":\"three_pump_test_rain_v1\",\"valveOn\":") +
      (anyPumpOn() ? "true" : "false") +
      ",\"manualOpen\":" + (anyPumpOn() ? "true" : "false") +
      ",\"nPumpOn\":" + (pumpOn[0] ? "true" : "false") +
      ",\"pPumpOn\":" + (pumpOn[1] ? "true" : "false") +
      ",\"kPumpOn\":" + (pumpOn[2] ? "true" : "false") +
      ",\"gpioHigh\":" + (digitalRead(PUMP_PINS[0]) == HIGH ? "true" : "false") +
      ",\"gpioLevel\":" + String(digitalRead(PUMP_PINS[0])) +
      ",\"gpio4High\":" + (digitalRead(PUMP_PINS[0]) == HIGH ? "true" : "false") +
      ",\"gpio4Level\":" + String(digitalRead(PUMP_PINS[0])) +
      ",\"gpio5High\":" + (digitalRead(PUMP_PINS[1]) == HIGH ? "true" : "false") +
      ",\"gpio5Level\":" + String(digitalRead(PUMP_PINS[1])) +
      ",\"gpio6High\":" + (digitalRead(PUMP_PINS[2]) == HIGH ? "true" : "false") +
      ",\"gpio6Level\":" + String(digitalRead(PUMP_PINS[2])) +
      // Legacy fields continue to reflect IN1 while older displays migrate.
      ",\"gpio42High\":" + (digitalRead(PUMP_PINS[0]) == HIGH ? "true" : "false") +
      ",\"gpio42Level\":" + String(digitalRead(PUMP_PINS[0])) +
      ",\"activeHigh\":true,\"mode\":\"manual\"" +
      ",\"runSeconds\":" + String(runSeconds(0)) +
      ",\"nRunSeconds\":" + String(runSeconds(0)) +
      ",\"pRunSeconds\":" + String(runSeconds(1)) +
      ",\"kRunSeconds\":" + String(runSeconds(2)) +
      ",\"maxRunS\":" + String(MAX_TEST_RUN_MS / 1000UL) +
      ",\"rainTips\":" + String(tips) +
      ",\"rainMm\":" + String(tips * RAIN_MM_PER_TIP, 1) +
      ",\"error\":\"" + jsonEscape(lastError) +
      "\",\"lastCommandId\":\"" + jsonEscape(lastCommandId) + "\"}");
}

void handleCommand(const String &json) {
  const int commandAt = json.indexOf("\"command\":{");
  if (commandAt < 0) return;
  const String command = json.substring(commandAt);
  lastCommandId = jsonString(command, "id", lastCommandId);
  const String action = jsonString(command, "action");

  if (action == "pump_test") {
    const int index = pumpIndex(jsonString(command, "pump"));
    const String requested = jsonString(command, "manual_action");
    if (index < 0) {
      lastError = "bad_pump";
    } else if (requested == "open" || requested == "on") {
      setPump(index, true, "");
    } else if (requested == "close" || requested == "off") {
      setPump(index, false, "manual_close");
    } else {
      lastError = "bad_manual_action";
    }
  } else if (action == "manual") {
    const String requested = jsonString(command, "manual_action");
    if (requested == "close" || requested == "off") {
      stopAll("manual_close");
    } else if (requested == "open" || requested == "on") {
      // Backward compatibility: the former single-pump start controls IN1/N.
      setPump(0, true, "");
    } else {
      lastError = "bad_manual_action";
    }
  } else if (action == "mode" || action == "config") {
    stopAll(action == "mode" ? "mode_changed" : "config_updated");
    controlMode = "manual";
    saveMode();
  } else if (action == "sensor") {
    // Sensor frames are accepted for protocol compatibility but never start a pump.
  } else {
    lastError = "unsupported_command";
  }
  reportSerialState();
}

void pollSerial() {
  while (Serial.available()) {
    const char character = static_cast<char>(Serial.read());
    if (character == '\r') continue;
    if (character != '\n') {
      if (serialLine.length() < 900) serialLine += character;
      else serialLine = "";
      continue;
    }
    if (serialLine == "STATUS") reportSerialState();
    else if (serialLine.indexOf("\"command\":{") >= 0) handleCommand(serialLine);
    serialLine = "";
  }
}

void setup() {
  Serial.begin(115200);
  delay(200);
  for (int index = 0; index < PUMP_COUNT; ++index) {
    pinMode(PUMP_PINS[index], OUTPUT);
    gpio_set_drive_capability(static_cast<gpio_num_t>(PUMP_PINS[index]), GPIO_DRIVE_CAP_3);
    digitalWrite(PUMP_PINS[index], LOW);
  }
  pinMode(RAIN_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(RAIN_PIN), onRainTip, FALLING);
  stopAll("boot_safe_off");
  saveMode();
  reportSerialState();
}

void loop() {
  pollSerial();
  // A start command records pumpStartedAt inside pollSerial(). Read the
  // current time afterwards so unsigned subtraction cannot wrap and trigger
  // an immediate false max-runtime shutdown.
  const unsigned long now = millis();
  for (int index = 0; index < PUMP_COUNT; ++index) {
    if (pumpOn[index] && now - pumpStartedAt[index] >= MAX_TEST_RUN_MS) {
      setPump(index, false, "max_runtime_reached");
      reportSerialState();
    }
  }
  delay(20);
}
