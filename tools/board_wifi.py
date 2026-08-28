import os
import io
import shlex
import time
from pathlib import Path

import paramiko


HOST = os.environ.get("ZHIRUN_BOARD_HOST", "192.168.1.10")
USER = os.environ.get("ZHIRUN_BOARD_USER", "root")
PASSWORD = os.environ.get("ZHIRUN_BOARD_PASSWORD", "root")
SSID = os.environ["ZHIRUN_WIFI_SSID"]
WIFI_PASSWORD = os.environ["ZHIRUN_WIFI_PASSWORD"]
PROJECT = Path(__file__).resolve().parent.parent


def run(client, command):
    _, stdout, stderr = client.exec_command(command)
    output = stdout.read().decode(errors="replace").strip()
    error = stderr.read().decode(errors="replace").strip()
    exit_status = stdout.channel.recv_exit_status()
    if exit_status != 0:
        raise RuntimeError(error or output or f"remote command exited with {exit_status}")
    return output


def wpa_value(value):
    return shlex.quote('"' + value.replace('"', '\\"') + '"')


def ensure_supplicant(client):
    try:
        status = run(client, "wpa_cli -i wlan0 status")
    except RuntimeError:
        status = ""
    if "wpa_state=" in status:
        return

    def config_value(value):
        return value.replace("\\", "\\\\").replace('"', '\\"')

    config = (
        "ctrl_interface=/var/run/wpa_supplicant\n"
        "update_config=1\n"
        "country=CN\n"
        "network={\n"
        '    ssid="%s"\n'
        '    psk="%s"\n'
        "    scan_ssid=1\n"
        "}\n"
    ) % (config_value(SSID), config_value(WIFI_PASSWORD))
    sftp = client.open_sftp()
    sftp.putfo(io.BytesIO(config.encode("utf-8")), "/tmp/zhirun-wpa.conf")
    sftp.chmod("/tmp/zhirun-wpa.conf", 0o600)
    sftp.close()
    run(
        client,
        "rm -f /etc/wpa_supplicant.conf; "
        "install -m 600 /tmp/zhirun-wpa.conf /etc/wpa_supplicant.conf; "
        "killall wpa_supplicant 2>/dev/null || true; "
        "mkdir -p /var/run/wpa_supplicant; "
        "wpa_supplicant -B -i wlan0 -c /etc/wpa_supplicant.conf "
        "-P /run/wpa_supplicant.wlan0.pid",
    )
    time.sleep(2)


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
    try:
        ensure_supplicant(client)
        network_id = ""
        for line in run(client, "wpa_cli -i wlan0 list_networks").splitlines()[1:]:
            fields = line.split("\t")
            if len(fields) >= 2 and fields[1] == SSID:
                network_id = fields[0]
                break
        if not network_id:
            network_id = run(client, "wpa_cli -i wlan0 add_network").splitlines()[-1]
        if not network_id.isdigit():
            raise RuntimeError("wpa_cli add_network failed: " + network_id)
        run(client, "wpa_cli -i wlan0 set_network %s ssid %s" % (network_id, wpa_value(SSID)))
        run(client, "wpa_cli -i wlan0 set_network %s psk %s" % (network_id, wpa_value(WIFI_PASSWORD)))
        run(client, "wpa_cli -i wlan0 set_network %s scan_ssid 1" % network_id)
        run(client, "wpa_cli -i wlan0 enable_network %s" % network_id)
        run(client, "wpa_cli -i wlan0 select_network %s" % network_id)
        run(client, "wpa_cli -i wlan0 save_config")
        run(
            client,
            "test -e /userdata/wlan0.interfaces.backup || "
            "cp -a /etc/network/interfaces.d/wlan0 /userdata/wlan0.interfaces.backup; "
            "if [ -f /var/run/wpa_supplicant/wpa_supplicant.conf ]; then "
            "cp /var/run/wpa_supplicant/wpa_supplicant.conf /etc/wpa_supplicant.conf; fi; "
            "chmod 600 /etc/wpa_supplicant.conf; "
            "cp /etc/wpa_supplicant.conf /userdata/zhirun-wpa.conf; "
            "chmod 600 /userdata/zhirun-wpa.conf; "
            "printf 'iface wlan0 inet manual\\n' > /etc/network/interfaces.d/wlan0; sync",
        )

        sftp = client.open_sftp()
        sftp.put(str(PROJECT / "deploy" / "zhirun-wifi.init"), "/tmp/S97zhirun-wifi")
        sftp.close()
        run(
            client,
            "install -m 755 /tmp/S97zhirun-wifi /etc/init.d/S97zhirun-wifi; "
            "/etc/init.d/S97zhirun-wifi restart; sync",
        )

        status = ""
        for _ in range(30):
            try:
                status = run(client, "wpa_cli -i wlan0 status")
            except RuntimeError:
                status = ""
            if "wpa_state=COMPLETED" in status:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Wi-Fi association timed out")

        time.sleep(3)
        print(status)
        print(run(client, "ip -4 addr show dev wlan0; ip route"))
        print(run(client, "wget -T 5 -qO- http://8.145.49.45/data | head -c 160; echo"))
    finally:
        client.close()


if __name__ == "__main__":
    main()
