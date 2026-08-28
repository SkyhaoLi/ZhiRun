import os
from pathlib import Path

import paramiko


PROJECT = Path(__file__).resolve().parent.parent
HOST = os.environ.get("ZHIRUN_BOARD_HOST", "192.168.1.10")
PASSWORD = os.environ.get("ZHIRUN_BOARD_PASSWORD", "root")


def run(client, command, timeout=60, check=True):
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read().decode("utf-8", "replace")
    error = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if check and code:
        raise RuntimeError("%s\n%s" % (output, error))
    return output + error


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="root", password=PASSWORD, timeout=10,
                   look_for_keys=False, allow_agent=False)
    stopped = False
    try:
        path = run(client, "grep 'USB role detected: rs485=' /userdata/zhirun-rk3506-collector.log | tail -1 | cut -d= -f2").strip()
        if not path or not run(client, "test -c %s && echo yes" % path).strip():
            raise RuntimeError("no active RS485 serial port found")
        sftp = client.open_sftp()
        sftp.put(str(PROJECT / "edge" / "modbus_readonly_probe.py"), "/tmp/modbus_readonly_probe.py")
        sftp.close()
        run(client, "/etc/init.d/S98zhirun-collector stop")
        stopped = True
        print("RS485_PORT=" + path)
        print(run(client, "python3 /tmp/modbus_readonly_probe.py --port %s" % path, timeout=90))
    finally:
        if stopped:
            run(client, "/etc/init.d/S98zhirun-collector start", check=False)
        client.close()


if __name__ == "__main__":
    main()
