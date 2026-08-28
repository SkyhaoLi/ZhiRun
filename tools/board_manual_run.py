import paramiko

def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect("192.168.1.10", username="root", password="root", timeout=10,
              look_for_keys=False, allow_agent=False)
    cmd = "rm -f /tmp/zhirun_hmi.log; /oem/usr/bin/zhirun_hmi_demo >/tmp/zhirun_hmi.log 2>&1 & echo PID=$!; sleep 2; ps | grep zhirun_hmi | grep -v grep || true; echo LOG; cat /tmp/zhirun_hmi.log"
    _, out, err = c.exec_command(cmd)
    print(out.read().decode(errors="replace"))
    print(err.read().decode(errors="replace"))
    c.close()

if __name__ == "__main__":
    main()
