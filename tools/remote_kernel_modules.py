import os
from pathlib import Path

import paramiko


HOST = os.environ.get("ZHIRUN_BUILD_HOST", "8.145.49.45")
PASSWORD = os.environ["ZHIRUN_BUILD_PASSWORD"]
ROOT = "/opt/linux-6.1.118"
CROSS = "/opt/rk3506-toolchain/gcc-arm-10.3-2021.07-x86_64-arm-none-linux-gnueabihf/host/bin/arm-buildroot-linux-gnueabihf-"
DOWNLOADS = Path(__file__).resolve().parent.parent / "downloads"


def run(client, command, timeout=1800):
    print("$", command)
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read().decode(errors="replace")
    error = stderr.read().decode(errors="replace")
    print(output)
    if error:
        print(error)
    code = stdout.channel.recv_exit_status()
    if code:
        raise RuntimeError("remote build failed with exit code %d" % code)


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        HOST,
        username="root",
        password=PASSWORD,
        timeout=15,
        look_for_keys=False,
        allow_agent=False,
    )
    run(
        client,
        "set -e; command -v flex >/dev/null || {{ apt-get update; apt-get install -y flex bison; }}; "
        "test -f {root}/Makefile || {{ "
        "curl -fL --retry 5 --retry-delay 2 "
        "https://github.com/gregkh/linux/archive/refs/tags/v6.1.118.tar.gz "
        "-o /tmp/linux-6.1.118.tar.gz; "
        "tar -C /opt -xzf /tmp/linux-6.1.118.tar.gz; }}; "
        "cd {root}; "
        "make ARCH=arm CROSS_COMPILE={cross} multi_v7_defconfig; "
        "scripts/config --enable MODULES --enable MODULE_UNLOAD --enable SMP "
        "--enable PREEMPT --disable PREEMPT_NONE --disable PREEMPT_VOLUNTARY "
        "--enable THUMB2_KERNEL --enable ARM_PATCH_PHYS_VIRT "
        "--enable USB_SERIAL --module USB_SERIAL_CH341; "
        "make ARCH=arm CROSS_COMPILE={cross} olddefconfig modules_prepare; "
        "make -j4 ARCH=arm CROSS_COMPILE={cross} KBUILD_MODPOST_WARN=1 "
        "M=drivers/usb/serial modules; "
        "file drivers/usb/serial/ch341.ko; "
        "strings drivers/usb/serial/ch341.ko | grep -E '^(vermagic|depends)='".format(
            root=ROOT, cross=CROSS
        ),
    )
    DOWNLOADS.mkdir(exist_ok=True)
    sftp = client.open_sftp()
    for name in ("ch341.ko",):
        sftp.get(ROOT + "/drivers/usb/serial/" + name, str(DOWNLOADS / name))
    sftp.close()
    client.close()


if __name__ == "__main__":
    main()
