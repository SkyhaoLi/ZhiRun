import os
from pathlib import Path

import paramiko


PROJECT = Path(__file__).resolve().parent.parent
HOST = os.environ.get("ZHIRUN_BOARD_HOST", "192.168.1.10")
PASSWORD = os.environ.get("ZHIRUN_BOARD_PASSWORD", "root")

def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=10,
              look_for_keys=False, allow_agent=False)
    s = c.open_sftp()
    s.put(str(PROJECT / "downloads" / "zhirun_hmi_demo"), "/tmp/zhirun_hmi_demo.new")
    s.put(str(PROJECT / "downloads" / "liblvgl.so"), "/tmp/liblvgl.so.new")
    s.put(str(PROJECT / "deploy" / "zhirun-hmi.init"), "/tmp/S99zhirun-hmi")
    s.put(str(PROJECT / "deploy" / "zhirun-hmi-preinit"), "/tmp/S10lv_demo")
    s.close()
    cmd = (
        "test -e /userdata/zhirun_hmi_demo.pre-rain || "
        "cp -p /oem/usr/bin/zhirun_hmi_demo /userdata/zhirun_hmi_demo.pre-rain; "
        "test -e /userdata/S10lv_demo.pre-zhirun || "
        "cp -p /etc/init.d/pre_init/S10lv_demo /userdata/S10lv_demo.pre-zhirun; "
        "install -m 755 /tmp/zhirun_hmi_demo.new /oem/usr/bin/zhirun_hmi_demo; "
        "install -m 644 /tmp/liblvgl.so.new /oem/usr/lib/liblvgl.so; "
        "install -m 755 /tmp/S99zhirun-hmi /etc/init.d/S99zhirun-hmi; "
        "install -m 755 /tmp/S10lv_demo /etc/init.d/pre_init/S10lv_demo; "
        "/etc/init.d/S99zhirun-hmi restart; sleep 10; "
        "ps | grep zhirun_hmi_demo | grep -v grep; "
        "echo DRM_PID=$(fuser /dev/dri/card0 2>/dev/null); "
        "sed -n '1,120p' /tmp/zhirun_hmi.log"
    )
    _, out, err = c.exec_command(cmd)
    output = out.read().decode(errors="replace")
    error = err.read().decode(errors="replace")
    code = out.channel.recv_exit_status()
    print(output)
    print(error)
    if code or "zhirun_hmi_demo" not in output:
        raise RuntimeError("HMI deployment failed")
    c.close()

if __name__ == "__main__":
    main()
