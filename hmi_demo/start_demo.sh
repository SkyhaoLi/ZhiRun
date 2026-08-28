#!/bin/sh
set -e

APP=/oem/usr/bin/zhirun_hmi_demo
[ -x "$APP" ] || APP=/usr/bin/zhirun_hmi_demo
exec "$APP"
