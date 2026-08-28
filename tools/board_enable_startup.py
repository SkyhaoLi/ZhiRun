import paramiko

def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect("192.168.1.10", username="root", password="root", timeout=10,
              look_for_keys=False, allow_agent=False)
    script = """#! /bin/sh

start() {
    /oem/usr/bin/zhirun_hmi_demo &
}

case "$1" in
  start)
    start
    ;;
  *)
    echo "Usage: $0 {start}"
    exit 1
    ;;
esac

exit $?
"""
    s = c.open_sftp()
    with s.file("/etc/init.d/pre_init/S10lv_demo", "w") as f:
        f.write(script)
    s.chmod("/etc/init.d/pre_init/S10lv_demo", 0o755)
    s.close()
    _, out, err = c.exec_command("sed -n '1,80p' /etc/init.d/pre_init/S10lv_demo")
    print(out.read().decode())
    print(err.read().decode())
    c.close()

if __name__ == "__main__":
    main()
