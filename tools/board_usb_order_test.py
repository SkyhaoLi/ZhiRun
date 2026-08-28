import os
import time

import paramiko


HOST = os.environ.get("ZHIRUN_BOARD_HOST", "192.168.1.10")
PASSWORD = os.environ.get("ZHIRUN_BOARD_PASSWORD", "root")


def run(client, command, timeout=30, check=True):
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read().decode("utf-8", "replace")
    error = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    if check and code:
        raise RuntimeError("command failed (%d): %s\n%s" % (code, output, error))
    return output + error


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        HOST,
        username="root",
        password=PASSWORD,
        timeout=10,
        look_for_keys=False,
        allow_agent=False,
    )
    try:
        details = run(client, (
            "echo TTY_PATHS; "
            "for n in /sys/class/tty/ttyUSB*; do "
            "echo $(basename $n) $(readlink -f $n/device); done; "
            "echo DRIVERS; find /sys/bus -path '*/drivers/*/unbind' | grep -E 'ch341|usbserial'"
        ))
        print(details)
        interfaces = []
        for line in details.splitlines():
            if not line.startswith("ttyUSB"):
                continue
            device_path = line.split(maxsplit=1)[1]
            interfaces.append(device_path.split("/")[-2])
        if len(interfaces) != 2:
            raise RuntimeError("expected exactly two ttyUSB interfaces")

        pid_before = run(client, "cat /var/run/zhirun-rk3506-collector.pid").strip()
        print("COLLECTOR_PID_BEFORE=" + pid_before)
        driver = "/sys/bus/usb/drivers/ch341"
        for interface in interfaces:
            run(client, "echo %s > %s/unbind" % (interface, driver))
        for interface in reversed(interfaces):
            run(client, "echo %s > %s/bind" % (interface, driver))

        time.sleep(16)
        print(run(client, (
            "echo TTY_PATHS_AFTER; "
            "for n in /sys/class/tty/ttyUSB*; do "
            "echo $(basename $n) $(readlink -f $n/device); done; "
            "echo COLLECTOR_PID_AFTER=$(cat /var/run/zhirun-rk3506-collector.pid); "
            "echo COLLECTOR_FDS; ls -l /proc/$(cat /var/run/zhirun-rk3506-collector.pid)/fd "
            "2>/dev/null | grep ttyUSB || true; "
            "echo ROLE_LOG; tail -30 /userdata/zhirun-rk3506-collector.log | grep 'USB role'"
        )))
        pid_after = run(client, "cat /var/run/zhirun-rk3506-collector.pid").strip()
        if pid_after != pid_before:
            raise RuntimeError("collector restarted during USB order test")
    finally:
        client.close()


if __name__ == "__main__":
    main()
