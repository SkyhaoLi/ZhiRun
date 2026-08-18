#!/usr/bin/env python3
"""One-shot non-actuating ESP32 UART status probe."""
import fcntl
import os
import select
import struct
import termios
import time


PORT = "/dev/serial/by-path/platform-xhci-hcd.1.auto-usb-0:1.2:1.0-port0"


def main():
    fd = os.open(PORT, os.O_RDWR | os.O_NOCTTY)
    try:
        attrs = termios.tcgetattr(fd)
        attrs[0] = termios.IGNPAR
        attrs[1] = 0
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[3] = 0
        attrs[4] = termios.B115200
        attrs[5] = termios.B115200
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        mask = termios.TIOCM_DTR | termios.TIOCM_RTS
        fcntl.ioctl(fd, termios.TIOCMBIC, struct.pack("I", mask))
        time.sleep(0.2)
        fcntl.ioctl(fd, termios.TIOCMBIS, struct.pack("I", mask))
        time.sleep(1.0)
        os.write(fd, b'{"command":{"action":"manual","manual_action":"open"}}\n')
        end = time.monotonic() + 4.0
        data = bytearray()
        while time.monotonic() < end:
            ready, _, _ = select.select([fd], [], [], 0.5)
            if ready:
                data.extend(os.read(fd, 1024))
        print(bytes(data).decode("utf-8", "replace") if data else "NO_RESPONSE")
        os.write(fd, b'{"command":{"action":"manual","manual_action":"close"}}\n')
        time.sleep(0.5)
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
