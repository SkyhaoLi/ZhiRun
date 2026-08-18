#!/usr/bin/env python3
"""Forward Atlas collector uploads through the deployment computer.

Use only when the Atlas network cannot route to the public ZhiRun server.
The relay accepts /push from the Atlas LAN address and forwards it unchanged.
"""
import argparse
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class RelayHandler(BaseHTTPRequestHandler):
    upstream = ""
    allowed_host = ""

    def do_POST(self):
        if self.path != "/push" or self.client_address[0] != self.allowed_host:
            self.send_error(403)
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        try:
            # Windows Python may inherit a proxy configuration that makes
            # urllib stall on this private-to-public hop. curl uses the
            # machine's normal route and returns the VPS response promptly.
            result = subprocess.run(
                ["curl.exe", "-sS", "--connect-timeout", "4", "--max-time", "8",
                 "-X", "POST", "-H", "Content-Type: application/json",
                 "--data-binary", "@-", self.upstream + "/push", "-w", "\n%{http_code}"],
                input=body, capture_output=True, timeout=10,
            )
            output = result.stdout
            marker = output.rfind(b"\n")
            status = int(output[marker + 1:].strip() or b"502") if marker >= 0 else 502
            response_body = output[:marker] if marker >= 0 else output
            if result.returncode != 0:
                self.send_error(502, "upstream unavailable")
                return
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)
        except (OSError, subprocess.TimeoutExpired):
            self.send_error(502, "upstream unavailable")

    def log_message(self, format_string, *args):
        return


def main():
    parser = argparse.ArgumentParser(description="Atlas-to-ZhiRun push relay")
    parser.add_argument("--bind", required=True)
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--atlas-host", required=True)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--daemon", action="store_true")
    args = parser.parse_args()
    if args.daemon:
        command = [sys.executable, __file__, "--bind", args.bind, "--port", str(args.port),
                   "--atlas-host", args.atlas_host, "--upstream", args.upstream]
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        # WMI/terminal-launched processes can inherit a Windows job object;
        # break away so the relay survives the launcher session.
        flags |= getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        subprocess.Popen(command, creationflags=flags, close_fds=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    RelayHandler.upstream = args.upstream.rstrip("/")
    RelayHandler.allowed_host = args.atlas_host
    server = ThreadingHTTPServer((args.bind, args.port), RelayHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
