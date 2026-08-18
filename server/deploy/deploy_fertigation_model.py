#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""部署水肥策略模型和推理服务到智润服务器。"""
import os
import posixpath
import sys
import time

import paramiko


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SERVER_DIR = os.path.join(ROOT, "server")
MODEL_DIR = os.path.join(ROOT, "灌溉模型", "灌溉模型")


def load_env():
    path = os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def mkdirs(sftp, remote_path):
    current = ""
    for part in remote_path.split("/"):
        if not part:
            continue
        current = posixpath.join(current, part)
        try:
            sftp.mkdir(current)
        except IOError:
            pass


def main():
    load_env()
    host = os.environ.get("ZHIRUN_HOST") or sys.exit("缺少 ZHIRUN_HOST")
    user = os.environ.get("ZHIRUN_USER") or sys.exit("缺少 ZHIRUN_USER")
    password = os.environ.get("ZHIRUN_PWD") or sys.exit("缺少 ZHIRUN_PWD")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, password=password, timeout=30)
    sftp = ssh.open_sftp()
    remote_root = "zhirun-infer"
    for local, remote in [
        (os.path.join(SERVER_DIR, "infer_server.py"), remote_root + "/infer_server.py"),
        (os.path.join(SERVER_DIR, "index.html"), "index.html"),
    ]:
        mkdirs(sftp, posixpath.dirname(remote))
        sftp.put(local, remote)
        print("uploaded", remote)
    for root, _, files in os.walk(MODEL_DIR):
        for name in files:
            local = os.path.join(root, name)
            relative = os.path.relpath(local, MODEL_DIR).replace("\\", "/")
            remote = remote_root + "/model/" + relative
            mkdirs(sftp, posixpath.dirname(remote))
            sftp.put(local, remote)
            print("uploaded", remote)
    service_local = os.path.join(SERVER_DIR, "deploy", "zhirun-infer.service")
    mkdirs(sftp, ".config/systemd/user")
    sftp.put(service_local, ".config/systemd/user/zhirun-infer.service")
    sftp.close()
    commands = [
        "python3 -m pip install --break-system-packages -r ~/zhirun-infer/model/requirements.txt",
        "systemctl --user daemon-reload",
        "systemctl --user enable zhirun-infer.service",
        "systemctl --user restart zhirun-infer.service",
        "systemctl --user restart zhirun.service",
        "loginctl enable-linger $USER 2>/dev/null || true",
    ]
    for command in commands:
        _, out, err = ssh.exec_command(command)
        stdout, stderr = out.read().decode("utf-8", "ignore").strip(), err.read().decode("utf-8", "ignore").strip()
        print(command, "\n", stdout or stderr)
    time.sleep(3)
    _, out, _ = ssh.exec_command("curl -s http://127.0.0.1:10001/health")
    print("health:", out.read().decode("utf-8", "ignore"))
    ssh.close()


if __name__ == "__main__":
    main()
