#!/usr/bin/env python3
"""Execute one Atlas-to-ESP32 line command over a CH340 UART."""
import argparse
import fcntl
import json
import os
import select
import struct
import termios
import time


def transact(port, command, reset=True):
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
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
        if reset:
            mask = termios.TIOCM_DTR | termios.TIOCM_RTS
            fcntl.ioctl(fd, termios.TIOCMBIC, struct.pack("I", mask))
            time.sleep(0.2)
            fcntl.ioctl(fd, termios.TIOCMBIS, struct.pack("I", mask))
            time.sleep(0.35)
        os.write(fd, (json.dumps({"command": command}, separators=(",", ":")) + "\n").encode("utf-8"))
        end = time.monotonic() + 0.6
        data = bytearray()
        while time.monotonic() < end:
            ready, _, _ = select.select([fd], [], [], min(0.5, end - time.monotonic()))
            if ready:
                data.extend(os.read(fd, 1024))
                # ESP32 prints a diagnostic "Command:" line before the JSON
                # acknowledgement. Do not return on that line: the caller
                # needs the complete STATE response to know the pump command
                # was actually applied.
                marker = data.find(b"STATE ")
                if marker >= 0:
                    try:
                        json.JSONDecoder().raw_decode(
                            bytes(data[marker + 6:]).decode("utf-8", "replace").lstrip())
                        break
                    except json.JSONDecodeError:
                        pass
        print(bytes(data).decode("utf-8", "replace"), end="")
    finally:
        os.close(fd)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True)
    parser.add_argument("--command", required=True)
    parser.add_argument("--no-reset", action="store_true")
    args = parser.parse_args()
    transact(args.port, json.loads(args.command), reset=not args.no_reset)
