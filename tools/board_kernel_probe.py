import os

import paramiko


HOST = os.environ.get("ZHIRUN_BOARD_HOST", "192.168.1.10")
USER = os.environ.get("ZHIRUN_BOARD_USER", "root")
PASSWORD = os.environ.get("ZHIRUN_BOARD_PASSWORD", "root")


def run(client, command):
    _, stdout, stderr = client.exec_command(command, timeout=30)
    output = stdout.read().decode(errors="replace")
    error = stderr.read().decode(errors="replace")
    print(f"$ {command}\n{output}", end="")
    if error:
        print(error, end="")


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        HOST,
        username=USER,
        password=PASSWORD,
        timeout=10,
        look_for_keys=False,
        allow_agent=False,
    )

    commands = [
        "uname -a; cat /proc/version; cat /proc/cmdline",
        "ls -la /boot /usr/lib/modules/$(uname -r); find /boot /usr/src /usr/lib/modules/$(uname -r) -maxdepth 3 -type f 2>/dev/null",
        "test -r /proc/config.gz && zcat /proc/config.gz | grep -E 'CONFIG_(USB_SERIAL|MODVERSIONS|MODULE_UNLOAD|LOCALVERSION)' || true",
        "find / -xdev -type f -name '.config' -o -name 'config-$(uname -r)' 2>/dev/null",
        "cat /sys/firmware/devicetree/base/model 2>/dev/null; echo; tr '\\0' '\\n' </sys/firmware/devicetree/base/compatible 2>/dev/null",
        "for n in /sys/class/tty/ttyS*; do echo ==== $n; readlink -f $n/device; cat $n/device/of_node/status 2>/dev/null; done",
        "for f in /proc/device-tree/aliases/serial*; do echo -n $f=; tr '\\0' '\\n' <$f; done 2>/dev/null",
        "find /sys/firmware/devicetree/base -type f -name status 2>/dev/null | while read f; do v=$(cat $f); [ \"$v\" = okay ] && echo $f; done | grep -E 'serial|uart' || true",
        "find /sys/bus/usb/devices -maxdepth 2 -type f -name modalias -exec sh -c 'echo -n $1=; cat $1' sh {} \\; 2>/dev/null",
        "for m in $(find /usr/lib/modules/$(uname -r) -type f -name '*.ko' | head -5); do echo ==== $m; strings $m | grep -E '^(vermagic|depends|srcversion)='; done",
    ]
    for command in commands:
        run(client, command)

    client.close()


if __name__ == "__main__":
    main()
