# Production services

The server units in this directory run the public dashboard and fertigation
inference service on Ubuntu. Atlas-only units retain their hardware-specific
network and collector behavior. Runtime credentials are not stored here.

## Ubuntu public server

The public server uses `/opt/zhirun` and the dedicated `zhirun` service user.
Install the source there, create the user, install Python dependencies from
`灌溉模型/灌溉模型/requirements.txt`, then install and enable:

```bash
install -m 0644 deploy/zhirun-server.service deploy/zhirun-infer.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now zhirun-server.service zhirun-infer.service
```

Set `ZHIRUN_PUSH_TOKEN` in `/etc/zhirun/server.env` if Atlas upload
authentication is enabled.
For the repository deployment helpers, copy `deploy/server.env.example` to the
repository root as `.env` and replace only the local SSH password and token.

## Atlas production services

Atlas runtime credentials remain in
`/home/HwHiAiUser/.config/zhirun-atlas.env` and are not stored here.

## Install

Run these commands as root on the Atlas after deploying the application source
(do not install the Ubuntu-only public server units there):

```bash
install -m 0755 deploy/zhirun-boot-prepare /usr/local/sbin/
install -m 0755 deploy/zhirun-healthcheck /usr/local/sbin/
install -m 0755 deploy/zhirun-esp-safe-init /usr/local/sbin/
install -m 0644 deploy/zhirun-boot-prepare.service deploy/zhirun-atlas-collector.service deploy/zhirun-healthcheck.service deploy/zhirun-healthcheck.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable zhirun-boot-prepare.service zhirun-server.service
systemctl enable zhirun-atlas-collector.service zhirun-healthcheck.timer
systemctl restart zhirun-server.service zhirun-atlas-collector.service
systemctl start zhirun-healthcheck.timer
```

The collector starts only after network preparation and an ESP32 safe-mode
initialization attempt. The health timer checks the local dashboard, collector
log freshness, and the H3C uplink once per minute, restarting or renewing the
affected component when necessary.
