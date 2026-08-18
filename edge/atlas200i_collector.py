#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Atlas 200I DK A2 sensor collector for ZhiRun.

It polls one USB-RS485 bus, counts the rain gauge on a Linux GPIO,
and posts the same sensor keys to the existing ZhiRun /push endpoint.

Dependencies: Python 3 standard library only.
"""
import argparse
import fcntl
import json
import os
import select
import socket
import struct
import subprocess
import sys
import termios
import threading
import time
from datetime import date
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = "/etc/zhirun-atlas.env"
DEFAULTS = {
    "ZHIRUN_ATLAS_SERVER": "http://127.0.0.1:10000",
    "ZHIRUN_ATLAS_TOKEN": "",
    "ZHIRUN_ATLAS_DEVICE_ID": "atlas-200i-dk-a2",
    "ZHIRUN_ATLAS_DEVICE_NAME": "Atlas 200I DK A2",
    # Optional presentation address for the dashboard. It does not affect
    # the routed address used to reach the public server.
    "ZHIRUN_DISPLAY_IP": "",
    "ZHIRUN_RS485_PORT": "/dev/ttyUSB0",
    "ZHIRUN_RS485_BAUD": "4800",
    "ZHIRUN_MODBUS_TIMEOUT_S": "0.35",
    # Keep command polling responsive while retaining a modest sensor rate.
    "ZHIRUN_POLL_INTERVAL_S": "0.5",
    "ZHIRUN_PUSH_TIMEOUT_S": "1.0",
    "ZHIRUN_SOIL_ADDR": "2",
    "ZHIRUN_TH_ADDR": "1",
    "ZHIRUN_CO2_ADDR": "3",
    "ZHIRUN_LIGHT_ADDR": "5",
    # Empty disables wind polling. On a shared bus its address must not
    # collide with the temperature/humidity sensor at address 1.
    "ZHIRUN_WIND_ADDR": "",
    "ZHIRUN_WIND_REG": "0",
    "ZHIRUN_WIND_BAUD": "",
    "ZHIRUN_WIND_FUNCTION": "4",
    "ZHIRUN_WIND_HOLD_S": "15",
    "ZHIRUN_SENSOR_HOLD_S": "60",
    "ZHIRUN_CLIMATE_SNAPSHOT_HOLD_S": "300",
    "ZHIRUN_SOIL_SNAPSHOT_HOLD_S": "300",
    "ZHIRUN_ENABLE_SOIL": "1",
    "ZHIRUN_ENABLE_TH": "1",
    "ZHIRUN_ENABLE_CO2": "1",
    "ZHIRUN_ENABLE_LIGHT": "1",
    "ZHIRUN_RAIN_GPIO": "16",
    "ZHIRUN_RAIN_EDGE": "falling",
    # Mechanical rain gauges can bounce for a few hundred milliseconds.
    # Count only one confirmed transition during this interval.
    "ZHIRUN_RAIN_DEBOUNCE_MS": "300",
    "ZHIRUN_RAIN_MM_PER_TIP": "0.3",
    "ZHIRUN_RAIN_STATE_FILE": "/var/lib/zhirun-atlas/rain_state.json",
    "ZHIRUN_GPS_ENABLE": "0",
    "ZHIRUN_GPS_PORT": "/dev/ttyAMA0",
    "ZHIRUN_GPS_BAUD": "9600",
    # Physical header pin 15 is board GPIO22 (SoC GPIO2_15). Linux sysfs
    # exposes GPIO2_15 as global line 79 (GPIO bank 2 base 64 + offset 15).
    # GPIO16 remains reserved for the rain gauge.
    "ZHIRUN_VALVE_GPIO": "79",
    "ZHIRUN_VALVE_ACTIVE_HIGH": "1",
    "ZHIRUN_VALVE_MAX_RUN_S": "180",
    # Valve commands are interactive controls; keep their network poll well
    # below the sensor collection cadence so a button press feels immediate.
    "ZHIRUN_VALVE_POLL_S": "0.1",
    # A USB-connected ESP32 receives valve commands over this serial device.
    # Empty preserves the legacy Atlas GPIO controller.
    "ZHIRUN_ESP_SERIAL_PORT": "",
    "ZHIRUN_ESP_SERIAL_BAUD": "115200",
}


def load_config(path):
    values = dict(DEFAULTS)
    for candidate in (ROOT / ".env", Path(path)):
        if not candidate.exists():
            continue
        for raw in candidate.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key in values:
                values[key] = value.strip()
    for key in values:
        if key in os.environ:
            values[key] = os.environ[key]
    return values


def int_value(config, key):
    return int(config[key], 0)


def float_value(config, key):
    return float(config[key])


def modbus_crc(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def signed16(value):
    return value - 0x10000 if value & 0x8000 else value


def network_snapshot(server_url):
    """Return the active routed interface without changing its configuration."""
    result = {"networkType": "ethernet", "networkInterface": None,
              "networkIp": None, "networkGateway": None, "networkConnected": False}
    try:
        for line in Path("/proc/net/route").read_text(encoding="ascii").splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 3 and fields[1] == "00000000":
                result["networkInterface"] = fields[0]
                gateway = int(fields[2], 16).to_bytes(4, "little")
                result["networkGateway"] = socket.inet_ntoa(gateway)
                break
        target = urlparse(server_url)
        host = target.hostname
        if host:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.connect((host, target.port or 80))
                result["networkIp"] = probe.getsockname()[0]
                result["networkConnected"] = True
    except (OSError, ValueError):
        pass
    return result


class PosixSerial:
    SPEEDS = {4800: termios.B4800, 9600: termios.B9600, 19200: termios.B19200,
              38400: termios.B38400, 115200: termios.B115200}

    def __init__(self, path, baud, reset_on_open=False):
        self.path = path
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY)
        self.baud = None
        self.rx_buffer = bytearray()
        self.set_baud(baud)
        if reset_on_open:
            self._reset_esp32_uart()

    def _reset_esp32_uart(self):
        """Release the CH340 auto-reset lines into normal ESP32 run mode."""
        mask = termios.TIOCM_DTR | termios.TIOCM_RTS
        fcntl.ioctl(self.fd, termios.TIOCMBIC, struct.pack("I", mask))
        time.sleep(0.2)
        fcntl.ioctl(self.fd, termios.TIOCMBIS, struct.pack("I", mask))
        time.sleep(1.0)

    def set_baud(self, baud):
        if baud not in self.SPEEDS:
            raise ValueError("unsupported RS485 baud: %s" % baud)
        if self.baud == baud:
            return
        attrs = termios.tcgetattr(self.fd)
        attrs[0] = termios.IGNPAR
        attrs[1] = 0
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[3] = 0
        attrs[4] = self.SPEEDS[baud]
        attrs[5] = self.SPEEDS[baud]
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        termios.tcflush(self.fd, termios.TCIOFLUSH)
        self.baud = baud

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def transaction(self, request, timeout):
        os.write(self.fd, request)
        deadline = time.monotonic() + timeout
        response = bytearray()
        while time.monotonic() < deadline:
            # Once bytes have arrived, a short silent interval marks the end
            # of an RTU response. Do not consume the whole timeout on every
            # successful request; it leaves less time for the next device.
            remaining = max(0, deadline - time.monotonic())
            ready, _, _ = select.select([self.fd], [], [], min(remaining, 0.03 if response else remaining))
            if not ready:
                if response:
                    break
                continue
            chunk = os.read(self.fd, 256)
            if chunk:
                response.extend(chunk)
        return bytes(response)


class ModbusBus:
    def __init__(self, config):
        self.serial = PosixSerial(config["ZHIRUN_RS485_PORT"], int_value(config, "ZHIRUN_RS485_BAUD"))
        self.timeout = float_value(config, "ZHIRUN_MODBUS_TIMEOUT_S")

    def read_holding(self, address, start_register, count, function=3, baud=None, attempts=1):
        if baud is not None:
            self.serial.set_baud(baud)
        body = bytes((address, function, start_register >> 8, start_register & 0xFF,
                      count >> 8, count & 0xFF))
        crc = modbus_crc(body)
        expected = count * 2
        frame_size = expected + 5
        request = body + bytes((crc & 0xFF, crc >> 8))
        for _ in range(attempts):
            response = self.serial.transaction(request, self.timeout)
            self.serial.rx_buffer.extend(response)
            if len(self.serial.rx_buffer) > 512:
                del self.serial.rx_buffer[:-128]
            # USB-RS485 adapters may surface a stale byte or split a response
            # into chunks. Find a complete CRC-valid response instead of
            # trusting byte 0.
            for start in range(0, len(self.serial.rx_buffer) - frame_size + 1):
                frame = self.serial.rx_buffer[start:start + frame_size]
                if frame[:3] != bytes((address, function, expected)):
                    continue
                received_crc = frame[-2] | (frame[-1] << 8)
                if modbus_crc(frame[:-2]) != received_crc:
                    continue
                del self.serial.rx_buffer[:start + frame_size]
                return [(frame[3 + i] << 8) | frame[4 + i] for i in range(0, expected, 2)]
            time.sleep(0.03)
        return None

    def close(self):
        self.serial.close()


class RainCounter:
    """Linux sysfs GPIO watcher. Atlas GPIO line numbering is board-image specific."""
    def __init__(self, gpio, edge, state_file, debounce_ms=300):
        self.gpio = gpio
        self.edge = str(edge).strip().lower()
        if self.edge not in ("falling", "rising", "both", "none"):
            raise ValueError("ZHIRUN_RAIN_EDGE must be falling, rising, both, or none")
        self.debounce_s = max(0.0, float(debounce_ms) / 1000.0)
        self.state_file = Path(state_file)
        self.lock = threading.Lock()
        self.total, self.day, self.day_base = self._load_state()
        self.available = False
        self.value_file = None
        self.last_level = None
        self.last_tip_at = 0.0
        self.stop_event = threading.Event()

    def _load_state(self):
        try:
            state = json.loads(self.state_file.read_text(encoding="utf-8"))
            return int(state.get("total", 0)), state.get("day", str(date.today())), int(state.get("day_base", 0))
        except (OSError, ValueError, TypeError):
            return 0, str(date.today()), 0

    def _save_state(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_file.with_suffix(".tmp")
        temporary.write_text(json.dumps({"total": self.total, "day": self.day, "day_base": self.day_base}), encoding="utf-8")
        os.replace(temporary, self.state_file)

    def _setup(self):
        gpio_path = Path("/sys/class/gpio/gpio%d" % self.gpio)
        if not gpio_path.exists():
            Path("/sys/class/gpio/export").write_text(str(self.gpio), encoding="ascii")
            for _ in range(20):
                if gpio_path.exists():
                    break
                time.sleep(0.05)
        (gpio_path / "direction").write_text("in", encoding="ascii")
        (gpio_path / "edge").write_text(self.edge, encoding="ascii")
        self.value_file = open(gpio_path / "value", "r", encoding="ascii", buffering=1)
        self.value_file.read()
        self.value_file.seek(0)
        self.last_level = self._read_level()
        self.available = True

    def _read_level(self):
        self.value_file.seek(0)
        value = self.value_file.read().strip()
        return value if value in ("0", "1") else None

    def _is_trigger(self, previous, current):
        if previous is None or current is None or previous == current:
            return False
        return self.edge == "both" or (self.edge == "falling" and previous == "1" and current == "0") or (self.edge == "rising" and previous == "0" and current == "1")

    def start(self):
        # systemd can start this collector before the Atlas GPIO controllers
        # have finished probing. Keep retrying instead of permanently losing
        # rain collection after one early "invalid GPIO" error.
        threading.Thread(target=self._run, name="rain-gpio", daemon=True).start()

    def _run(self):
        last_error = None
        while not self.stop_event.is_set():
            try:
                self._setup()
                self._watch()
            except OSError as exc:
                self.available = False
                message = str(exc)
                if message != last_error:
                    print("[RAIN] GPIO unavailable: %s" % exc, file=sys.stderr)
                    last_error = message
                self.stop_event.wait(1.0)
            finally:
                if self.value_file:
                    self.value_file.close()
                    self.value_file = None

    def _watch(self):
        watcher = select.poll()
        watcher.register(self.value_file.fileno(), select.POLLPRI | select.POLLERR)
        while not self.stop_event.is_set():
            if not watcher.poll(1000):
                continue
            current = self._read_level()
            previous = self.last_level
            self.last_level = current
            if not self._is_trigger(previous, current):
                continue
            now_mono = time.monotonic()
            if now_mono - self.last_tip_at < self.debounce_s:
                continue
            # The trigger is accepted only after a real, configured edge.
            # This matters for reed switches: their active level can be a
            # very short pulse, so waiting for it to remain active would
            # discard actual tipping-bucket measurements.
            self.last_tip_at = time.monotonic()
            with self.lock:
                self.total += 1
                self._save_state()

    def snapshot(self, mm_per_tip):
        with self.lock:
            today = str(date.today())
            if self.day != today:
                self.day, self.day_base = today, self.total
                self._save_state()
            tips = max(0, self.total - self.day_base)
        return {"rainTips": tips, "rainMm": round(tips * mm_per_tip, 2)} if self.available else {"rainTips": None, "rainMm": None}

    def close(self):
        self.stop_event.set()
        if self.value_file:
            self.value_file.close()


class NmeaGps:
    """Read standard NMEA messages from the BeiDou/GNSS receiver."""
    def __init__(self, config):
        self.enabled = enabled(config, "ZHIRUN_GPS_ENABLE")
        self.port = config["ZHIRUN_GPS_PORT"].strip()
        self.baud = int_value(config, "ZHIRUN_GPS_BAUD")
        self.lock = threading.Lock()
        self.data = {"latitude": None, "longitude": None, "gpsSatellites": None,
                     "gpsSpeed": None, "gpsConnected": 0, "gpsFixQuality": 0}
        self.stop_event = threading.Event()

    @staticmethod
    def _coordinate(raw, hemisphere):
        if not raw or not hemisphere:
            return None
        try:
            degrees = int(raw[:2] if hemisphere in {"N", "S"} else raw[:3])
            value = degrees + float(raw[2:] if hemisphere in {"N", "S"} else raw[3:]) / 60.0
            return -value if hemisphere in {"S", "W"} else value
        except (TypeError, ValueError):
            return None

    def _parse(self, line):
        if not line.startswith("$"):
            return
        sentence, separator, checksum = line[1:].partition("*")
        if separator:
            try:
                expected = int(checksum[:2], 16)
            except ValueError:
                return
            actual = 0
            for char in sentence:
                actual ^= ord(char)
            if actual != expected:
                return
        fields = sentence.split(",")
        if not fields or len(fields[0]) < 3:
            return
        kind = fields[0][-3:]
        with self.lock:
            self.data["gpsConnected"] = 1
            if kind == "RMC" and len(fields) >= 8:
                if fields[2] == "A":
                    latitude = self._coordinate(fields[3], fields[4])
                    longitude = self._coordinate(fields[5], fields[6])
                    if latitude is not None and longitude is not None:
                        self.data.update({"latitude": round(latitude, 6), "longitude": round(longitude, 6)})
                    try:
                        self.data["gpsSpeed"] = round(float(fields[7]) * 1.852, 1)
                    except ValueError:
                        pass
            elif kind == "GGA" and len(fields) >= 8:
                try:
                    self.data["gpsFixQuality"] = int(fields[6] or 0)
                    self.data["gpsSatellites"] = int(fields[7]) if fields[7] else None
                except ValueError:
                    pass

    def _run(self):
        serial = None
        try:
            serial = PosixSerial(self.port, self.baud)
            buffer = bytearray()
            while not self.stop_event.is_set():
                ready, _, _ = select.select([serial.fd], [], [], 1.0)
                if not ready:
                    continue
                buffer.extend(os.read(serial.fd, 512))
                while b"\n" in buffer:
                    raw, _, buffer = buffer.partition(b"\n")
                    self._parse(raw.decode("ascii", "ignore").strip())
        except (OSError, ValueError) as exc:
            print("[GPS] UART unavailable: %s" % exc, file=sys.stderr)
        finally:
            if serial:
                serial.close()

    def start(self):
        if self.enabled and self.port:
            threading.Thread(target=self._run, name="gps-nmea", daemon=True).start()

    def snapshot(self):
        with self.lock:
            return dict(self.data)

    def close(self):
        self.stop_event.set()


class ValveController:
    """Execute queued water-pump commands through a Linux sysfs GPIO.

    The output is intentionally opt-in: an empty ZHIRUN_VALVE_GPIO reports
    the missing wiring instead of driving an arbitrary board pin.
    """
    def __init__(self, config):
        self.config = config
        self.esp_port = config.get("ZHIRUN_ESP_SERIAL_PORT", "").strip()
        self.esp_serial = None
        self.esp_state = {}
        self.esp_rx_buffer = ""
        self.esp_ready = False
        raw_gpio = config.get("ZHIRUN_VALVE_GPIO", "").strip()
        self.gpio = int(raw_gpio, 0) if raw_gpio else None
        self.active_high = config.get("ZHIRUN_VALVE_ACTIVE_HIGH", "1").strip().lower() not in {"0", "false", "no"}
        self.max_run_s = max(1.0, float_value(config, "ZHIRUN_VALVE_MAX_RUN_S"))
        self.poll_s = max(0.05, float_value(config, "ZHIRUN_VALVE_POLL_S"))
        self.server = config["ZHIRUN_ATLAS_SERVER"].rstrip("/")
        self.device_id = quote(config["ZHIRUN_ATLAS_DEVICE_ID"], safe="")
        self.token = config["ZHIRUN_ATLAS_TOKEN"]
        self.value_path = None
        self.available = False
        self.error = "valve_gpio_not_configured" if self.gpio is None else "valve_gpio_unavailable"
        self.valve_on = False
        # Safe startup mode: automatic control must be explicitly selected
        # after the relay and ESP32 link are confirmed healthy.
        self.mode = "manual"
        self.open_count = 0
        self.started_at = 0.0
        self.last_poll = 0.0
        self.wifi_networks = []
        self.wifi_scanned_at = 0
        self.wifi_error = ""

    def _nmcli(self, args, timeout=20):
        """Run NetworkManager without exposing credentials in logs or shell."""
        return subprocess.run(["nmcli", *args], text=True, capture_output=True,
                              timeout=timeout, check=False)

    def _wifi_device(self):
        try:
            result = self._nmcli(["-t", "-f", "DEVICE,TYPE", "device", "status"], timeout=8)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode:
            return None
        for line in result.stdout.splitlines():
            parts = line.split(":", 1)
            if len(parts) == 2 and parts[1] == "wifi":
                return parts[0]
        return None

    @staticmethod
    def _split_nmcli(line):
        fields, field, escaped = [], [], False
        for char in line:
            if escaped:
                field.append(char)
                escaped = False
            elif ord(char) == 92:
                escaped = True
            elif char == ":":
                fields.append("".join(field))
                field = []
            else:
                field.append(char)
        fields.append("".join(field))
        return fields

    def _scan_wifi(self):
        device = self._wifi_device()
        if not device:
            self.wifi_networks = []
            self.wifi_error = "wireless_adapter_not_found"
            self.wifi_scanned_at = int(time.time())
            return
        try:
            result = self._nmcli(["-t", "--escape", "yes", "-f", "SSID,SIGNAL,SECURITY",
                                  "device", "wifi", "list", "ifname", device, "--rescan", "yes"], timeout=20)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.wifi_error = "wifi_scan_failed: %s" % exc
            return
        if result.returncode:
            self.wifi_error = (result.stderr.strip() or "wifi_scan_failed")[:160]
            return
        networks = {}
        for line in result.stdout.splitlines():
            ssid, signal, security = (self._split_nmcli(line) + ["", "", ""])[:3]
            if not ssid:
                continue
            try:
                rssi = int(signal) * 2 - 100
            except ValueError:
                rssi = -100
            item = {"ssid": ssid, "rssi": rssi, "lock": bool(security and security != "--")}
            if ssid not in networks or item["rssi"] > networks[ssid]["rssi"]:
                networks[ssid] = item
        self.wifi_networks = sorted(networks.values(), key=lambda item: item["rssi"], reverse=True)
        self.wifi_scanned_at = int(time.time())
        self.wifi_error = ""

    def _connect_wifi(self, ssid, password):
        device = self._wifi_device()
        if not device:
            self.wifi_error = "wireless_adapter_not_found"
            return
        args = ["device", "wifi", "connect", ssid, "ifname", device]
        if password:
            args.extend(["password", password])
        try:
            result = self._nmcli(args, timeout=45)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.wifi_error = "wifi_connect_failed: %s" % exc
            return
        self.wifi_error = "" if result.returncode == 0 else (result.stderr.strip() or "wifi_connect_failed")[:160]
        self._scan_wifi()

    def _wifi_status(self):
        try:
            result = self._nmcli(["-t", "--escape", "yes", "-f", "ACTIVE,SSID", "device", "wifi"], timeout=8)
        except (OSError, subprocess.TimeoutExpired):
            return False, ""
        if result.returncode:
            return False, ""
        for line in result.stdout.splitlines():
            active, ssid = (self._split_nmcli(line) + [""])[:2]
            if active == "yes" and ssid:
                return True, ssid
        return False, ""

    def _setup(self):
        if self.esp_port:
            self.esp_serial = PosixSerial(self.esp_port, int_value(self.config, "ZHIRUN_ESP_SERIAL_BAUD"), reset_on_open=True)
            self.available = True
            self.error = ""
            return
        if self.gpio is None:
            return
        gpio_path = Path("/sys/class/gpio/gpio%d" % self.gpio)
        if not gpio_path.exists():
            Path("/sys/class/gpio/export").write_text(str(self.gpio), encoding="ascii")
            for _ in range(20):
                if gpio_path.exists():
                    break
                time.sleep(0.05)
        (gpio_path / "direction").write_text("out", encoding="ascii")
        self.value_path = gpio_path / "value"
        self.available = True
        self._write(False)
        self.error = ""

    def start(self):
        try:
            self._setup()
        except (OSError, ValueError) as exc:
            self.available = False
            self.error = "valve_gpio_unavailable: %s" % exc
            print("[VALVE] %s" % self.error, file=sys.stderr)

    def _write(self, enabled):
        if self.esp_serial is not None:
            command = {"command": {"action": "manual", "manual_action": "open" if enabled else "close"}}
            os.write(self.esp_serial.fd, (json.dumps(command, separators=(",", ":")) + "\n").encode("utf-8"))
            return
        if not self.available or self.value_path is None:
            return
        level = enabled if self.active_high else not enabled
        self.value_path.write_text("1" if level else "0", encoding="ascii")

    def _state(self):
        run_s = int(max(0, time.monotonic() - self.started_at)) if self.valve_on else 0
        wifi_connected, wifi_ssid = self._wifi_status()
        # Report the electrical level, not only the logical pump state. This
        # lets the UI distinguish active-high and active-low driver modules.
        gpio_high = (self.valve_on == self.active_high) if self.available else None
        state = {"mode": self.mode, "manualOpen": self.valve_on, "valveOn": self.valve_on,
                "runS": run_s, "openCount": self.open_count, "gpio": self.gpio,
                "gpioHigh": gpio_high, "gpio42High": gpio_high, "error": self.error,
                "wifiNetworks": self.wifi_networks, "wifiScannedAt": self.wifi_scanned_at,
                "wifiError": self.wifi_error, "wifiConnected": wifi_connected, "wifiSsid": wifi_ssid}
        state.update(self.esp_state)
        return state

    def _forward_to_esp(self, command, allow_retry=True):
        if self.esp_serial is None:
            return False
        # CH340 on the Atlas needs a clean DTR/RTS transaction for control
        # commands. A short-lived helper is more reliable than a long-held fd.
        if command.get("action") in {"manual", "mode", "config"}:
            helper = ROOT / "edge" / "esp_uart_command.py"
            self.esp_serial.close()
            self.esp_serial = None
            args = [sys.executable, str(helper), "--port", self.esp_port,
                    "--command", json.dumps(command, separators=(",", ":"))]
            if self.esp_ready:
                args.append("--no-reset")
            result = subprocess.run(args,
                                    text=True, capture_output=True, timeout=8, check=False)
            self.esp_serial = PosixSerial(self.esp_port, int_value(self.config, "ZHIRUN_ESP_SERIAL_BAUD"), reset_on_open=False)
            state_start = result.stdout.rfind("STATE ")
            if state_start >= 0:
                try:
                    # ESP32 diagnostic text may contain literal "\\n" after
                    # the JSON. Decode exactly one JSON object instead of
                    # requiring the whole UART capture to be valid JSON.
                    self.esp_state, _ = json.JSONDecoder().raw_decode(
                        result.stdout[state_start + 6:].lstrip())
                    was_on = self.valve_on
                    self.valve_on = bool(self.esp_state.get("valveOn", False))
                    if self.valve_on and not was_on:
                        reported_run_s = max(0.0, float(self.esp_state.get("runSeconds", 0) or 0))
                        self.started_at = time.monotonic() - reported_run_s
                    elif not self.valve_on:
                        self.started_at = 0.0
                    self.mode = self.esp_state.get("mode", self.mode)
                    self.error = self.esp_state.get("error", "")
                    self.esp_ready = True
                    print("[ESP] state %s" % json.dumps(self.esp_state, separators=(",", ":")))
                    return True
                except json.JSONDecodeError:
                    pass
            print("[ESP] command failed: %s" % (result.stderr.strip() or result.stdout.strip() or result.returncode))
            return False
        print("[ESP] tx %s" % json.dumps(command, separators=(",", ":")))
        # A CH340 reconnect can leave boot/diagnostic bytes in the receive
        # queue. Discard those bytes so they cannot prefix the first STATE
        # response and make the line parser miss it.
        try:
            termios.tcflush(self.esp_serial.fd, termios.TCIFLUSH)
        except OSError:
            pass
        os.write(self.esp_serial.fd, (json.dumps({"command": command}, separators=(",", ":")) + "\n").encode("utf-8"))
        # CH340/ESP32 can need over one second after an auto-reset before its
        # first UART reply is available. Keep the command pending long enough
        # to receive the complete STATE line.
        deadline = time.monotonic() + 4.0
        got_state = False
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self.esp_serial.fd], [], [], max(0, deadline - time.monotonic()))
            if not ready:
                break
            self.esp_rx_buffer += os.read(self.esp_serial.fd, 512).decode("utf-8", "replace")
            # Treat UART input as a stream: boot text and partial reads may
            # precede STATE, so do not require STATE to begin a line.
            state_start = self.esp_rx_buffer.find("STATE ")
            if state_start >= 0:
                try:
                    state, end = json.JSONDecoder().raw_decode(
                        self.esp_rx_buffer[state_start + 6:].lstrip())
                    self.esp_state = state
                    was_on = self.valve_on
                    self.valve_on = bool(state.get("valveOn", False))
                    if self.valve_on and not was_on:
                        reported_run_s = max(0.0, float(state.get("runSeconds", 0) or 0))
                        self.started_at = time.monotonic() - reported_run_s
                    elif not self.valve_on:
                        self.started_at = 0.0
                    self.mode = state.get("mode", self.mode)
                    self.error = state.get("error", "")
                    print("[ESP] state %s" % json.dumps(state, separators=(",", ":")))
                    got_state = True
                    self.esp_rx_buffer = self.esp_rx_buffer[state_start + 6 + end:]
                except json.JSONDecodeError:
                    # Keep partial JSON until the next read completes it.
                    if state_start:
                        self.esp_rx_buffer = self.esp_rx_buffer[state_start:]
            elif len(self.esp_rx_buffer) > 2048:
                self.esp_rx_buffer = self.esp_rx_buffer[-256:]
        if not got_state and allow_retry and command.get("action") in {"manual", "mode", "config"}:
            print("[ESP] no state response; reopening UART and retrying command")
            self.esp_serial.close()
            self.esp_serial = PosixSerial(self.esp_port, int_value(self.config, "ZHIRUN_ESP_SERIAL_BAUD"), reset_on_open=True)
            return self._forward_to_esp(command, allow_retry=False)
        return True

    def _report(self):
        body = json.dumps({"state": self._state(), "token": self.token}, separators=(",", ":")).encode("utf-8")
        request = Request(self.server + "/api/devices/" + self.device_id + "/valve/result", data=body,
                          headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=float_value(self.config, "ZHIRUN_PUSH_TIMEOUT_S")):
                pass
        except (OSError, URLError) as exc:
            print("[VALVE] state report failed: %s" % exc, file=sys.stderr)

    def _fetch_command(self):
        url = self.server + "/api/devices/" + self.device_id + "/valve/commands/next?token=" + quote(self.token, safe="")
        with urlopen(url, timeout=float_value(self.config, "ZHIRUN_PUSH_TIMEOUT_S")) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload.get("command")

    def _apply(self, command):
        action = command.get("action") if isinstance(command, dict) else None
        if self.esp_serial is not None and action in {"manual", "mode", "config"}:
            if self._forward_to_esp(command):
                # Keep the Atlas state coherent even when the ESP32 response
                # is delayed or unavailable. Hardware remains fail-safe; a
                # later STATE frame will replace this optimistic state.
                if action == "mode" and command.get("mode") in {"manual", "auto"}:
                    self.mode = command["mode"]
                    if self.mode == "manual":
                        # The ESP32 mode handler already closes the pump as
                        # its safety action. Do not enqueue a second CLOSE:
                        # it can otherwise overtake a following OPEN click.
                        self.valve_on = False
                elif action == "manual" and command.get("manual_action") in {"open", "close"}:
                    self.mode = "manual"
                    enabled = command["manual_action"] == "open"
                    if enabled and not self.valve_on:
                        self.open_count += 1
                        self.started_at = time.monotonic()
                    self.valve_on = enabled
                    if not enabled:
                        self.started_at = 0.0
                        self._write(False)
                return
        if action == "mode":
            mode = command.get("mode")
            if mode in {"manual", "auto"}:
                self.mode = mode
            return
        if action == "network_scan":
            self._scan_wifi()
            return
        if action == "network_config":
            self._connect_wifi(str(command.get("ssid") or ""), str(command.get("password") or ""))
            return
        if action != "manual":
            return
        requested = command.get("manual_action")
        if requested not in {"open", "close"}:
            self.error = "bad_manual_action"
            return
        if not self.available:
            self.error = self.error or "valve_gpio_unavailable"
            return
        enabled = requested == "open"
        self._write(enabled)
        if enabled and not self.valve_on:
            self.open_count += 1
            self.started_at = time.monotonic()
        self.valve_on = enabled
        self.mode = "manual"
        self.error = ""

    def poll(self):
        now = time.monotonic()
        # Manual mode stays open until the user explicitly closes it. Keep the
        # timeout as an automatic-mode fail-safe only.
        if self.valve_on and self.mode == "auto" and now - self.started_at >= self.max_run_s:
            self._write(False)
            self.valve_on = False
            self.error = "max_run_timeout"
            self._report()
        if now - self.last_poll < self.poll_s:
            return
        self.last_poll = now
        try:
            command = self._fetch_command()
            if command:
                self._apply(command)
                self._report()
        except (OSError, ValueError, URLError, json.JSONDecodeError) as exc:
            print("[VALVE] command poll failed: %s" % exc, file=sys.stderr)

    def close(self):
        if self.available:
            try:
                self._write(False)
                self._report()
            except OSError:
                pass


def empty_payload():
    return {key: None for key in ("airTemp", "airHum", "co2", "lux", "soilMoist", "soilTemp",
                                   "soilPH", "n", "p", "k", "windSpeed", "rainTips", "rainMm",
                                   "latitude", "longitude", "gpsSatellites", "gpsSpeed",
                                   "gpsConnected", "gpsFixQuality")}


_last_wind = {"value": None, "timestamp": 0.0}
_last_sensor_values = {}
_last_climate_snapshot = {"data": None, "timestamp": 0.0}
_last_soil_snapshot = {"data": None, "timestamp": 0.0}


def enabled(config, key):
    return config.get(key, "1").strip().lower() not in {"0", "false", "no"}


def read_registers(bus, address, start_register, count, function=3):
    values = bus.read_holding(address, start_register, count, function=function, attempts=3)
    if values is not None or count == 1:
        return values
    # Some soil probes reject a multi-register request but support the same
    # registers individually. Fall back without sending any write command.
    values = []
    for offset in range(count):
        single = bus.read_holding(address, start_register + offset, 1, function=function, attempts=3)
        if single is None:
            return None
        values.append(single[0])
    return values


def collect(bus, config, rain, gps):
    data = empty_payload()
    soil = read_registers(bus, int_value(config, "ZHIRUN_SOIL_ADDR"), 0, 7) if enabled(config, "ZHIRUN_ENABLE_SOIL") else None
    if soil and 0 <= soil[0] <= 1000 and 20 <= soil[3] <= 140:
        soil_moist = soil[0] / 10.0
        # An uncovered capacitive probe commonly reports a few raw percentage
        # points of electrical noise. Treat that deadband as dry/zero so an
        # idle probe does not make the dashboard flicker between 0 and 2.x%.
        if soil_moist < 3.0:
            soil_moist = 0.0
        data.update({"soilMoist": soil_moist, "soilTemp": signed16(soil[1]) / 10.0,
                     "soilPH": soil[3] / 10.0, "n": soil[4], "p": soil[5], "k": soil[6]})
    th = bus.read_holding(int_value(config, "ZHIRUN_TH_ADDR"), 0, 2, attempts=3) if enabled(config, "ZHIRUN_ENABLE_TH") else None
    if th:
        data.update({"airHum": th[0] / 10.0, "airTemp": signed16(th[1]) / 10.0})
    co2 = bus.read_holding(int_value(config, "ZHIRUN_CO2_ADDR"), 0, 1, attempts=3) if enabled(config, "ZHIRUN_ENABLE_CO2") else None
    if co2:
        data["co2"] = co2[0]
    light = bus.read_holding(int_value(config, "ZHIRUN_LIGHT_ADDR"), 0, 2, attempts=3) if enabled(config, "ZHIRUN_ENABLE_LIGHT") else None
    if light:
        data["lux"] = light[1]
    wind_address = config["ZHIRUN_WIND_ADDR"].strip()
    if wind_address:
        wind_baud = int_value(config, "ZHIRUN_WIND_BAUD") if config["ZHIRUN_WIND_BAUD"].strip() else None
        wind_function = int_value(config, "ZHIRUN_WIND_FUNCTION")
        wind = bus.read_holding(int(wind_address, 0), int_value(config, "ZHIRUN_WIND_REG"), 1,
                                function=wind_function, baud=wind_baud, attempts=5)
        # Wind meters in this family may expose the same register through
        # either holding (0x03) or input (0x04) reads. Both are read-only.
        if wind is None and wind_function in (3, 4):
            fallback_function = 4 if wind_function == 3 else 3
            wind = bus.read_holding(int(wind_address, 0), int_value(config, "ZHIRUN_WIND_REG"), 1,
                                    function=fallback_function, baud=wind_baud, attempts=3)
        if wind_baud is not None:
            bus.serial.set_baud(int_value(config, "ZHIRUN_RS485_BAUD"))
        if wind:
            data["windSpeed"] = wind[0] / 10.0
            _last_wind.update({"value": data["windSpeed"], "timestamp": time.monotonic()})
        elif _last_wind["value"] is not None and time.monotonic() - _last_wind["timestamp"] <= float_value(config, "ZHIRUN_WIND_HOLD_S"):
            data["windSpeed"] = _last_wind["value"]
    # Preserve the last CRC-valid environmental frame through brief RS485
    # dropouts. A new reading replaces it immediately; a sustained outage is
    # still exposed as null after the configured hold interval.
    now = time.monotonic()
    climate_keys = ("airTemp", "airHum", "co2", "lux")
    if all(data[key] is not None for key in climate_keys):
        _last_climate_snapshot["data"] = {key: data[key] for key in climate_keys}
        _last_climate_snapshot["timestamp"] = now
    elif (_last_climate_snapshot["data"] is not None and
          now - _last_climate_snapshot["timestamp"] <= float_value(config, "ZHIRUN_CLIMATE_SNAPSHOT_HOLD_S")):
        # A louver-box display is a single synchronized measurement: do not
        # combine fields from separate, partially successful polling rounds.
        data.update(_last_climate_snapshot["data"])
    soil_keys = ("soilMoist", "soilTemp", "soilPH", "n", "p", "k")
    if all(data[key] is not None for key in soil_keys):
        _last_soil_snapshot["data"] = {key: data[key] for key in soil_keys}
        _last_soil_snapshot["timestamp"] = now
    elif (_last_soil_snapshot["data"] is not None and
          now - _last_soil_snapshot["timestamp"] <= float_value(config, "ZHIRUN_SOIL_SNAPSHOT_HOLD_S")):
        data.update(_last_soil_snapshot["data"])
    hold_seconds = float_value(config, "ZHIRUN_SENSOR_HOLD_S")
    for key in ("airTemp", "airHum", "co2", "lux", "soilMoist", "soilTemp", "soilPH", "n", "p", "k"):
        if data[key] is not None:
            _last_sensor_values[key] = (data[key], now)
        elif key in _last_sensor_values and now - _last_sensor_values[key][1] <= hold_seconds:
            data[key] = _last_sensor_values[key][0]
    data.update(rain.snapshot(float_value(config, "ZHIRUN_RAIN_MM_PER_TIP")))
    data.update(gps.snapshot())
    network = network_snapshot(config["ZHIRUN_ATLAS_SERVER"])
    display_ip = config["ZHIRUN_DISPLAY_IP"].strip()
    if display_ip:
        network["networkIp"] = display_ip
    data.update(network)
    return data


def push(config, payload):
    capabilities = ["rs485", "rain_gpio", "gps_nmea", "realtime_display"]
    if config.get("ZHIRUN_ESP_SERIAL_PORT", "").strip():
        capabilities.append("valve_control")
    body = {"token": config["ZHIRUN_ATLAS_TOKEN"], "device_id": config["ZHIRUN_ATLAS_DEVICE_ID"],
            "device_name": config["ZHIRUN_ATLAS_DEVICE_NAME"], "model": "Huawei Atlas 200I DK A2",
            "firmware_version": "atlas-collector-1.0", "data_source": "atlas",
            "capabilities": capabilities, "payload": payload}
    body["ip"] = payload.get("networkIp")
    body["network_type"] = payload.get("networkType")
    request = Request(config["ZHIRUN_ATLAS_SERVER"].rstrip("/") + "/push",
                      data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=float_value(config, "ZHIRUN_PUSH_TIMEOUT_S")) as response:
            if response.status != 200:
                raise URLError("server returned %s" % response.status)
    except (TimeoutError, socket.timeout) as exc:
        # Upload outages must not tear down a healthy RS485 session. The main
        # loop handles URLError as a retry while retaining the open bus.
        raise URLError("push timeout") from exc


def main():
    parser = argparse.ArgumentParser(description="ZhiRun Atlas 200I DK A2 collector")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="KEY=VALUE configuration file")
    parser.add_argument("--once", action="store_true", help="collect and print one frame without pushing")
    args = parser.parse_args()
    config = load_config(args.config)
    rain = RainCounter(int_value(config, "ZHIRUN_RAIN_GPIO"), config["ZHIRUN_RAIN_EDGE"], config["ZHIRUN_RAIN_STATE_FILE"], float_value(config, "ZHIRUN_RAIN_DEBOUNCE_MS"))
    rain.start()
    gps = NmeaGps(config)
    gps.start()
    valve = ValveController(config)
    valve.start()
    valve._report()
    bus = None
    next_cycle = time.monotonic()
    try:
        while True:
            try:
                # Valve commands must remain reachable even when the RS485
                # adapter is unplugged or a sensor times out.
                valve.poll()
                if bus is None:
                    bus = ModbusBus(config)
                    print("[RS485] connected to %s" % config["ZHIRUN_RS485_PORT"])
                payload = collect(bus, config, rain, gps)
                # Automatic watering is executed by the ESP32. Atlas only
                # forwards the latest sensor value; it never emits an
                # automatic open/close command of its own.
                if valve.esp_serial is not None and payload.get("soilMoist") is not None:
                    valve._forward_to_esp({"action": "sensor", "soil_moist": float(payload["soilMoist"])})
                print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
                if args.once:
                    return
                push(config, payload)
                # A sensor/RS485 round can take longer than the normal valve
                # poll interval. Check once immediately after it completes so
                # a command received during that round is not delayed again.
                valve.poll()
                # The first successful sensor push creates the device record
                # on the server. Report afterward so the UI also receives the
                # initial closed/fail-safe valve state before any button press.
                valve._report()
            except URLError as exc:
                # A temporary network outage must not reset a healthy RS485
                # session. Keep collecting and retry the upload next cycle.
                print("[PUSH] %s" % exc, file=sys.stderr)
            except (OSError, ValueError) as exc:
                print("[COLLECTOR] %s" % exc, file=sys.stderr)
                if bus:
                    bus.close()
                    bus = None
            next_cycle += float_value(config, "ZHIRUN_POLL_INTERVAL_S")
            delay = next_cycle - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            elif delay < -float_value(config, "ZHIRUN_POLL_INTERVAL_S"):
                # Do not build up a growing timing debt after a transport
                # timeout; resume the fixed cadence from the current time.
                next_cycle = time.monotonic()
    except KeyboardInterrupt:
        pass
    finally:
        if bus:
            bus.close()
        rain.close()
        gps.close()
        valve.close()


if __name__ == "__main__":
    main()
