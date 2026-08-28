import os
import json
import select
import termios
import time
from pathlib import Path


SPEEDS = {4800: termios.B4800, 115200: termios.B115200}


def crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def exchange(path, baud, request, timeout):
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        attrs = termios.tcgetattr(fd)
        attrs[0], attrs[1] = termios.IGNPAR, 0
        attrs[2], attrs[3] = termios.CS8 | termios.CREAD | termios.CLOCAL, 0
        attrs[4] = attrs[5] = SPEEDS[baud]
        attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        termios.tcflush(fd, termios.TCIOFLUSH)
        os.write(fd, request)
        data = bytearray()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            wait = max(0.0, min(0.05, deadline - time.monotonic()))
            ready, _, _ = select.select([fd], [], [], wait)
            if ready:
                data.extend(os.read(fd, 1024))
        return bytes(data)
    finally:
        os.close(fd)


def modbus_probe(path):
    body = bytes((1, 3, 0, 0, 0, 2))
    crc = crc16(body)
    response = exchange(path, 4800, body + bytes((crc & 255, crc >> 8)), 0.5)
    return len(response) >= 9 and response[:3] == bytes((1, 3, 4)) and crc16(response[-9:-2]) == response[-2] | response[-1] << 8


def main():
    for path in sorted(Path("/dev").glob("ttyUSB*")):
        response = exchange(str(path), 115200, b"STATUS\n", 1.5)
        esp = b"STATE " in response
        modbus = False if esp else modbus_probe(str(path))
        print("%s esp=%s modbus=%s response_bytes=%d" % (path, esp, modbus, len(response)))
        if esp:
            state = response[response.find(b"STATE "):].splitlines()[0]
            print(state.decode("utf-8", "replace"))
            command = {
                "command": {
                    "id": "usb-link-safe-close",
                    "action": "manual",
                    "manual_action": "close",
                }
            }
            acknowledgement = exchange(
                str(path),
                115200,
                (json.dumps(command, separators=(",", ":")) + "\n").encode(),
                1.5,
            )
            marker = acknowledgement.find(b"STATE ")
            if marker < 0:
                raise RuntimeError("ESP32 did not acknowledge safe-close command")
            print("SAFE_CLOSE_ACK " + acknowledgement[marker:].splitlines()[0].decode("utf-8", "replace"))
        elif response:
            print(response[:1200].decode("utf-8", "replace"))


if __name__ == "__main__":
    main()
