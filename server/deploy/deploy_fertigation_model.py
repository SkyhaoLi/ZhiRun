#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deploy the canonical V2 fertigation model to the public server."""
import os
import posixpath
import sys
import time

import paramiko


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SERVER_DIR = os.path.join(ROOT, "server")
MODEL_DIR = os.environ.get(
    "ZHIRUN_MODEL_SOURCE",
    os.path.join(ROOT, "灌溉模型", "灌溉模型"),
)


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
    current = "/" if remote_path.startswith("/") else ""
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
    if not os.path.isfile(os.path.join(MODEL_DIR, "scripts", "fertigation_model.py")):
        sys.exit("模型源目录无效: " + MODEL_DIR)
    host = os.environ.get("ZHIRUN_HOST") or sys.exit("缺少 ZHIRUN_HOST")
    user = os.environ.get("ZHIRUN_USER") or sys.exit("缺少 ZHIRUN_USER")
    password = os.environ.get("ZHIRUN_PWD") or sys.exit("缺少 ZHIRUN_PWD")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, password=password, timeout=30)
    sftp = ssh.open_sftp()
    remote_root = "/tmp/zhirun-infer-deploy"
    for local, remote in [
        (os.path.join(SERVER_DIR, "infer_server.py"), remote_root + "/infer_server.py"),
    ]:
        mkdirs(sftp, posixpath.dirname(remote))
        sftp.put(local, remote)
        print("uploaded", remote)
    for root, dirs, files in os.walk(MODEL_DIR):
        dirs[:] = [name for name in dirs if name not in {"__pycache__", ".pytest_cache", ".git"}]
        for name in files:
            if name.endswith((".pyc", ".pyo")):
                continue
            local = os.path.join(root, name)
            relative = os.path.relpath(local, MODEL_DIR).replace("\\", "/")
            remote = remote_root + "/model/" + relative
            mkdirs(sftp, posixpath.dirname(remote))
            sftp.put(local, remote)
            print("uploaded", remote)
    sftp.close()
    commands = [
        "/opt/zhirun/.venv/bin/python -m py_compile /tmp/zhirun-infer-deploy/infer_server.py",
        "/opt/zhirun/.venv/bin/python -m pip install -r /tmp/zhirun-infer-deploy/model/requirements.txt",
        "test -e /opt/zhirun/server/infer_server.py.pre-v2 || "
        "cp -p /opt/zhirun/server/infer_server.py /opt/zhirun/server/infer_server.py.pre-v2",
        "install -o zhirun -g zhirun -m 0644 /tmp/zhirun-infer-deploy/infer_server.py "
        "/opt/zhirun/server/infer_server.py",
        "mkdir -p '/opt/zhirun/灌溉模型/灌溉模型' && "
        "cp -a /tmp/zhirun-infer-deploy/model/. '/opt/zhirun/灌溉模型/灌溉模型/' && "
        "chown -R zhirun:zhirun '/opt/zhirun/灌溉模型/灌溉模型'",
        "systemctl restart zhirun-infer.service",
    ]
    for command in commands:
        _, out, err = ssh.exec_command(command)
        stdout, stderr = out.read().decode("utf-8", "ignore").strip(), err.read().decode("utf-8", "ignore").strip()
        print(command, "\n", stdout or stderr)
        code = out.channel.recv_exit_status()
        if code:
            raise RuntimeError("remote command failed (%s): %s" % (code, command))
    time.sleep(3)
    _, out, _ = ssh.exec_command(
        "systemctl is-active zhirun-infer.service && "
        "curl -fsS http://127.0.0.1:10001/health",
    )
    health = out.read().decode("utf-8", "ignore")
    code = out.channel.recv_exit_status()
    print("health:", health)
    if code or '"schema": "fertigation_v2_automatic_environment"' not in health:
        raise RuntimeError("V2 inference health check failed")
    ssh.close()


if __name__ == "__main__":
    main()
