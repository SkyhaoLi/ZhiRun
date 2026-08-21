# Atlas production services

This directory mirrors the boot and recovery services used by the production
Atlas 200I DK A2. Runtime credentials remain in
`/home/HwHiAiUser/.config/zhirun-atlas.env` and are not stored here.

## Install

Run these commands as root on the Atlas after deploying the application source:

```bash
install -m 0755 deploy/zhirun-boot-prepare /usr/local/sbin/
install -m 0755 deploy/zhirun-healthcheck /usr/local/sbin/
install -m 0755 deploy/zhirun-esp-safe-init /usr/local/sbin/
install -m 0644 deploy/*.service deploy/*.timer /etc/systemd/system/
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
