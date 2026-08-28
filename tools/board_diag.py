import paramiko

def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect("192.168.1.10", username="root", password="root", timeout=10,
              look_for_keys=False, allow_agent=False)
    commands = [
        "pid=$(pidof zhirun_hmi_demo 2>/dev/null || true); echo HMI_PID=$pid; test -n \"$pid\" && cat /proc/$pid/maps || true",
        "uname -a; cat /etc/os-release 2>/dev/null; uptime",
        "ip addr; ip route",
        "ifconfig -a 2>/dev/null || true; iwconfig 2>/dev/null || true; iw dev 2>/dev/null || true",
        "ps | grep -E 'wpa|dhcp|connman|network|rk3506_collector' | grep -v grep || true",
        "command -v wpa_supplicant; command -v wpa_cli; command -v iw; command -v iwconfig; command -v udhcpc",
        "ls -l /dev/ttyUSB* /dev/ttyACM* /dev/ttyS* 2>/dev/null || true",
        "lsusb 2>/dev/null || true; cat /sys/bus/usb/devices/1-1.1/idVendor 2>/dev/null; cat /sys/bus/usb/devices/1-1.1/idProduct 2>/dev/null",
        "lsmod | grep -E 'ch34|ftdi|cp210|usbserial' || true; dmesg | grep -Ei 'ttyUSB|ttyACM|ch34|ftdi|cp210|usb.serial' | tail -40",
        "find /lib/modules -type f -iname '*ch34*' -o -iname '*usbserial*' 2>/dev/null; zcat /proc/config.gz 2>/dev/null | grep -E 'CONFIG_USB_SERIAL(=|_)' || true",
        "cat /proc/version; cat /proc/modules | head -30; find / -type f -name '*.ko' 2>/dev/null | head -50",
        r"find /usr/lib/modules/$(uname -r) -type f \( -iname '*ch34*' -o -iname '*usbserial*' \) 2>/dev/null; ls -ld /usr/lib/modules/$(uname -r)/build /usr/src 2>/dev/null || true",
        "module=$(find / -type f -name '*.ko' 2>/dev/null | head -1); test -n \"$module\" && strings \"$module\" | grep -E 'vermagic=|depends=' || true",
        "wpa_cli -i wlan0 status 2>/dev/null || true; wpa_cli -i wlan0 scan 2>/dev/null || true; sleep 2; wpa_cli -i wlan0 scan_results 2>/dev/null | head -20",
        "grep -E '^(ctrl_interface|update_config)' /var/run/wpa_supplicant/wpa_supplicant.conf 2>/dev/null || true; grep -R 'wpa_supplicant' /etc/init.d /etc/network 2>/dev/null | head -30",
        "ls -l /var/run/wpa_supplicant/wpa_supplicant.conf /etc/network/interfaces.d/wlan0; grep -R -l 'SkyhaoLi' /etc /oem /userdata 2>/dev/null | head -20",
        r"ls /sys/bus/usb/drivers; find /sys/bus/usb/devices/1-1.1 -maxdepth 2 -type f -name 'bInterface*' -exec sh -c 'echo -n $1=; cat $1' sh {} \; 2>/dev/null",
        "ls -la /oem/usr/bin/rk3506_collector.py /etc/zhirun-rk3506.env /etc/init.d/S99zhirun-collector 2>/dev/null || true",
        "wget -T 5 -qO- http://8.145.49.45:10000/data 2>&1 | head -c 300; echo",
        "wget -T 5 -qO- http://8.145.49.45/data 2>&1 | head -c 500; echo",
        "ps | grep -E 'lv_demo|zhirun_hmi' | grep -v grep || true",
        "sed -n '1,240p' /tmp/zhirun_hmi.log 2>/dev/null",
        "cat /sys/class/graphics/fb0/blank 2>/dev/null || true",
        "cat /sys/class/graphics/fb0/virtual_size 2>/dev/null || true",
        "ls -l /dev/dri /dev/fb0",
        "dmesg | tail -80",
    ]
    for command in commands:
        _, out, err = c.exec_command(command)
        print("---", command)
        print(out.read().decode(errors="replace"))
        print(err.read().decode(errors="replace"))
    c.close()

if __name__ == "__main__":
    main()
