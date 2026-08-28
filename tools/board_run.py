import paramiko

def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect("192.168.1.10", username="root", password="root", timeout=10,
              look_for_keys=False, allow_agent=False)
    s = c.open_sftp()
    s.put("C:/Users/Skyha/Desktop/水肥一体/downloads/zhirun_hmi_demo", "/oem/usr/bin/zhirun_hmi_demo")
    s.chmod("/oem/usr/bin/zhirun_hmi_demo", 0o755)
    s.close()
    command = (
        "cp -p /etc/init.d/pre_init/S10lv_demo /userdata/S10lv_demo.backup 2>/dev/null || true; "
        "pid=$(pidof lv_demo 2>/dev/null || true); "
        "if [ -n \"$pid\" ]; then kill $pid; fi; sleep 1; "
        "nohup /oem/usr/bin/zhirun_hmi_demo >/tmp/zhirun_hmi.log 2>&1 & "
        "echo newpid=$!; sleep 5; ps; echo LOG; sed -n '1,100p' /tmp/zhirun_hmi.log"
    )
    _, out, err = c.exec_command(command)
    print(out.read().decode(errors="replace"))
    print(err.read().decode(errors="replace"))
    c.close()

if __name__ == "__main__":
    main()
