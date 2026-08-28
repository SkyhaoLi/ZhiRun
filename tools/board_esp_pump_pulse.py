"""Run a bounded ESP32 relay pulse directly from the RK3506B UART."""

import os
import shlex
import time
from pathlib import Path

import paramiko


PROJECT = Path(__file__).resolve().parent.parent
HOST = os.environ.get("ZHIRUN_BOARD_HOST", "192.168.1.10")
PASSWORD = os.environ.get("ZHIRUN_BOARD_PASSWORD", "root")
PORT = os.environ.get("ZHIRUN_ESP_FLASH_PORT", "/dev/ttyUSB1")


def run(client, command, timeout=15, check=True):
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read().decode("utf-8", "replace")
    error = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if check and code:
        raise RuntimeError("%s\n%s" % (output, error))
    return output + error


def command(action, command_id):
    payload = (
        '{"id":"%s","action":"pump_test","pump":"n",'
        '"manual_action":"%s"}' % (command_id, action)
    )
    return (
        "python3 /tmp/zhirun-esp-uart-command.py --port %s --no-reset --command %s"
        % (shlex.quote(PORT), shlex.quote(payload))
    )


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        HOST, username="root", password=PASSWORD, timeout=10,
        look_for_keys=False, allow_agent=False,
    )
    stopped = False
    try:
        sftp = client.open_sftp()
        sftp.put(str(PROJECT / "edge" / "esp_uart_command.py"), "/tmp/zhirun-esp-uart-command.py")
        sftp.close()
        run(client, "/etc/init.d/S98zhirun-collector stop")
        stopped = True
        print("OPEN", run(client, command("open", "direct-n-open")).strip())
        time.sleep(2)
        print("CLOSE", run(client, command("close", "direct-n-close")).strip())
    finally:
        if stopped:
            try:
                run(client, command("close", "direct-final-close"), check=False)
            finally:
                print(run(client, "/etc/init.d/S98zhirun-collector start; sleep 4; "
                                  "ps | grep rk3506_collector | grep -v grep", check=False).strip())
        client.close()


if __name__ == "__main__":
    main()
