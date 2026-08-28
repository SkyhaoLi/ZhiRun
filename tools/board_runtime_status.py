import os

import paramiko


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        os.environ.get("ZHIRUN_BOARD_HOST", "192.168.1.10"),
        username=os.environ.get("ZHIRUN_BOARD_USER", "root"),
        password=os.environ.get("ZHIRUN_BOARD_PASSWORD", "root"),
        timeout=10,
        look_for_keys=False,
        allow_agent=False,
    )
    commands = (
        "ls -l /dev/ttyUSB* /oem/usr/lib/modules/ch341.ko "
        "/etc/init.d/S03zhirun-ch341 /etc/init.d/S98zhirun-collector",
        "grep '^ch341 ' /proc/modules; ps | grep -E 'rk3506_collector|zhirun_hmi_demo' | grep -v grep",
        "wpa_cli -i wlan0 status | grep -E 'ssid=|wpa_state=|ip_address='",
        "tail -20 /tmp/zhirun_hmi.log",
        "tail -20 /userdata/zhirun-rk3506-collector.log",
    )
    for command in commands:
        _, stdout, stderr = client.exec_command(command, timeout=15)
        print(stdout.read().decode(errors="replace"), end="")
        error = stderr.read().decode(errors="replace")
        if error:
            print(error, end="")
    client.close()


if __name__ == "__main__":
    main()
