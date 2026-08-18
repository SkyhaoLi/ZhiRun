# -*- coding: utf-8 -*-
"""仅重启服务 (通过 systemctl, 文件已上传)

用法:
    复制项目根目录 `.env.example` 为 `.env`, 填写自己的服务器参数后运行。
    也可直接通过环境变量覆盖 `.env` 中的值。
"""
import paramiko, os, sys, time


def load_local_env():
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


load_local_env()

HOST = os.environ.get("ZHIRUN_HOST") or sys.exit("请设置 ZHIRUN_HOST (服务器地址)")
USER = os.environ.get("ZHIRUN_USER") or sys.exit("请设置 ZHIRUN_USER (服务器用户名)")
PWD  = os.environ.get("ZHIRUN_PWD")
if not PWD:
    sys.exit("请设置 ZHIRUN_PWD (服务器 SSH 密码)")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PWD, timeout=20)


def run(cmd):
    _in, out, err = ssh.exec_command(cmd)
    return out.read().decode("utf-8", "ignore").strip(), err.read().decode("utf-8", "ignore").strip()


PORT = os.environ.get("ZHIRUN_PORT", "10000").strip() or "10000"

# 重启用户级 systemd 服务 (本账号无 root, 服务以 systemctl --user 运行)
run("systemctl --user restart zhirun.service")
time.sleep(2)

o, _ = run("systemctl --user is-active zhirun.service")
print("SERVICE:", o)

o, _ = run(f"curl -s http://127.0.0.1:{PORT}/ | head -c 80")
print("PAGE:", o)
o, _ = run(f"curl -s http://127.0.0.1:{PORT}/data | head -c 320")
print("DATA:", o)

ssh.close()
print("DONE")
