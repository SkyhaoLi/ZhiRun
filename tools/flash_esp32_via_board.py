import os
import posixpath
import time
from pathlib import Path

import intelhex
import paramiko
import serial


PROJECT = Path(__file__).resolve().parent.parent
BUILD = PROJECT / "esp32_pump_controller" / ".pio" / "build" / "esp32-s3-devkitc-1"
PIO_HOME = Path.home() / ".platformio"
ESPTOOL = PIO_HOME / "packages" / "tool-esptoolpy" / "esptool"
BOOT_APP = PIO_HOME / "packages" / "framework-arduinoespressif32" / "tools" / "partitions" / "boot_app0.bin"
REMOTE_LIB = "/tmp/zhirun-esptool-20260826"
REMOTE_FW = "/tmp/zhirun-esp32-flash-20260826"
ESP_PORT = os.environ.get("ZHIRUN_ESP_FLASH_PORT", "/dev/ttyUSB1")


def connect():
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
    return client


def run(client, command, timeout=60):
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    channel = stdout.channel
    channel.settimeout(timeout)
    while not channel.exit_status_ready():
        if channel.recv_ready():
            print(channel.recv(4096).decode(errors="replace"), end="", flush=True)
        if channel.recv_stderr_ready():
            print(channel.recv_stderr(4096).decode(errors="replace"), end="", flush=True)
        time.sleep(0.05)
    while channel.recv_ready():
        print(channel.recv(4096).decode(errors="replace"), end="", flush=True)
    while channel.recv_stderr_ready():
        print(channel.recv_stderr(4096).decode(errors="replace"), end="", flush=True)
    code = channel.recv_exit_status()
    if code:
        raise RuntimeError("remote command failed with exit code %d" % code)


def upload_tree(sftp, local_root, remote_root):
    try:
        sftp.mkdir(remote_root)
    except OSError:
        pass
    for current, directories, files in os.walk(local_root):
        directories[:] = [name for name in directories if name != "__pycache__"]
        relative = Path(current).relative_to(local_root)
        remote_dir = remote_root if str(relative) == "." else posixpath.join(remote_root, relative.as_posix())
        if remote_dir != remote_root:
            try:
                sftp.mkdir(remote_dir)
            except OSError:
                pass
        for name in files:
            if name.endswith((".pyc", ".pyo")):
                continue
            sftp.put(str(Path(current) / name), posixpath.join(remote_dir, name))


def main():
    required = (BUILD / "bootloader.bin", BUILD / "partitions.bin", BUILD / "firmware.bin", BOOT_APP)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("missing firmware files: " + ", ".join(missing))

    client = connect()
    collector_stopped = False
    try:
        run(client, "mkdir -p %s %s" % (REMOTE_LIB, REMOTE_FW))
        sftp = client.open_sftp()
        upload_tree(sftp, ESPTOOL, REMOTE_LIB + "/esptool")
        upload_tree(sftp, Path(serial.__file__).resolve().parent, REMOTE_LIB + "/serial")
        upload_tree(sftp, Path(intelhex.__file__).resolve().parent, REMOTE_LIB + "/intelhex")
        for local, name in (
            (BUILD / "bootloader.bin", "bootloader.bin"),
            (BUILD / "partitions.bin", "partitions.bin"),
            (BOOT_APP, "boot_app0.bin"),
            (BUILD / "firmware.bin", "firmware.bin"),
        ):
            sftp.put(str(local), REMOTE_FW + "/" + name)
        sftp.close()

        tool = "PYTHONPATH=%s python3 -m esptool --chip esp32s3 --port %s" % (REMOTE_LIB, ESP_PORT)
        run(client, "PYTHONPATH=%s python3 -m esptool version" % REMOTE_LIB)
        run(client, "/etc/init.d/S98zhirun-collector stop")
        collector_stopped = True
        run(client, tool + " --baud 115200 chip_id", timeout=45)

        remote_backup = "/tmp/esp32s3-before-rk3506-usb-first1m.bin"
        run(client, tool + " --baud 115200 read_flash 0 0x100000 " + remote_backup, timeout=300)
        backup_dir = PROJECT / "esp32_backups"
        backup_dir.mkdir(exist_ok=True)
        backup = backup_dir / (
            "esp32s3-before-three-pump-flash-%s.bin" % time.strftime("%Y%m%d-%H%M%S")
        )
        sftp = client.open_sftp()
        sftp.get(remote_backup, str(backup))
        sftp.close()
        print("BACKUP=%s" % backup, flush=True)

        run(
            client,
            tool
            + " --baud 115200 write_flash --flash_mode dio --flash_freq 80m --flash_size 16MB "
            + "0x0 %s/bootloader.bin 0x8000 %s/partitions.bin " % (REMOTE_FW, REMOTE_FW)
            + "0xe000 %s/boot_app0.bin 0x10000 %s/firmware.bin" % (REMOTE_FW, REMOTE_FW),
            timeout=300,
        )
        run(client, "/etc/init.d/S98zhirun-collector start; sleep 12; ps | grep rk3506_collector | grep -v grep", timeout=25)
        collector_stopped = False
    finally:
        if collector_stopped:
            try:
                run(client, "/etc/init.d/S98zhirun-collector start")
            except Exception:
                pass
        client.close()


if __name__ == "__main__":
    main()
