import paramiko


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect("192.168.1.10", username="root", password="root", timeout=10,
                   look_for_keys=False, allow_agent=False)
    command = (
        "pidof zhirun_hmi_demo 2>/dev/null | xargs -r kill; "
        "pidof lv_demo 2>/dev/null | xargs -r kill; sleep 2; "
        "command -v lv_demo; ls -l /usr/bin/lv_demo /oem/usr/bin/lv_demo 2>/dev/null; "
        "rm -f /tmp/factory_lv_demo.log; "
        "nohup lv_demo >/tmp/factory_lv_demo.log 2>&1 & echo PID=$!; "
        "sleep 4; ps | grep lv_demo | grep -v grep || true; "
        "sed -n '1,100p' /tmp/factory_lv_demo.log"
    )
    _, stdout, stderr = client.exec_command(command)
    print(stdout.read().decode(errors="replace"))
    print(stderr.read().decode(errors="replace"))
    client.close()


if __name__ == "__main__":
    main()
