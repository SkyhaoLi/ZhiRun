#!/usr/bin/env python3
"""Read-only Modbus RTU probe for RK3506B sensor diagnostics."""
import argparse
import os
import select
import termios
import time


SPEEDS = {2400: termios.B2400, 4800: termios.B4800, 9600: termios.B9600,
          19200: termios.B19200, 38400: termios.B38400}


def crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


class Serial:
    def __init__(self, path):
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY)

    def set_baud(self, baud):
        attrs = termios.tcgetattr(self.fd)
        attrs[0], attrs[1], attrs[2], attrs[3] = termios.IGNPAR, 0, termios.CS8 | termios.CREAD | termios.CLOCAL, 0
        attrs[4] = attrs[5] = SPEEDS[baud]
        attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        termios.tcflush(self.fd, termios.TCIOFLUSH)

    def request(self, address, function, register, count):
        frame = bytes((address, function, register >> 8, register & 255, count >> 8, count & 255))
        checksum = crc16(frame)
        os.write(self.fd, frame + bytes((checksum & 255, checksum >> 8)))
        deadline, response = time.monotonic() + 0.22, bytearray()
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self.fd], [], [], deadline - time.monotonic())
            if not ready:
                break
            response.extend(os.read(self.fd, 256))
        return bytes(response)

    def close(self):
        os.close(self.fd)


def valid_frame(response, address, function):
    for start in range(len(response)):
        if response[start:start + 2] != bytes((address, function)):
            continue
        if start + 3 > len(response):
            continue
        length = 5 if response[start + 1] & 0x80 else response[start + 2] + 5
        frame = response[start:start + length]
        if len(frame) == length and crc16(frame[:-2]) == frame[-2] | frame[-1] << 8:
            return frame
    return None


def probe(port, baud, address, function, register, count):
    port.set_baud(baud)
    raw = port.request(address, function, register, count)
    frame = valid_frame(raw, address, function)
    if frame:
        print("OK baud=%d addr=%d func=%02X reg=%d count=%d frame=%s" %
              (baud, address, function, register, count, frame.hex()))


def main():
    parser = argparse.ArgumentParser(description="Read-only Modbus RTU probe")
    parser.add_argument("--port", required=True)
    parser.add_argument("--soil-only", action="store_true")
    args = parser.parse_args()
    serial = Serial(args.port)
    try:
        if args.soil_only:
            serial.set_baud(4800)
            for register in range(7):
                probe(serial, 4800, 2, 3, register, 1)
            return
        for baud in (4800, 9600, 19200, 2400, 38400):
            for address, function, count in ((1, 3, 2), (2, 3, 7)):
                probe(serial, baud, address, function, 0, count)
            for address in range(1, 11):
                for function in (3, 4):
                    probe(serial, baud, address, function, 0, 1)
    finally:
        serial.close()


if __name__ == "__main__":
    main()
