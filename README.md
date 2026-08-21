# ZhiRun Huawei Irrigation System

农田环境监测、水肥决策与水泵控制项目。华为 Atlas 200I DK A2 采集传感器数据并通过 USB 串口控制 ESP32，ESP32 负责水泵，公网服务提供仪表盘和控制接口。

## Architecture

```text
Browser <-> Public server <-> router <-> Atlas 200I DK A2 <-> USB serial <-> ESP32 pump controller
                                          |
                                          +-> RS485 environmental sensors
```

The collector and public upload client both run on the Atlas. The Atlas uses
its router-facing Ethernet interface to upload directly to the public server;
a developer PC is not part of the runtime data path. ESP32 is the authoritative
source for pump state. The Atlas forwards sensor and control messages, and the
public server relays commands and stores the latest state.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `server/` | Public dashboard, API relay, and fertigation inference service |
| `edge/` | Atlas sensor collector, UART transport, and systemd unit |
| `esp32_pump_controller/` | PlatformIO ESP32-S3 water-pump firmware |
| `fertigation_model/` | Fertigation decision model, scripts, test cases, and datasets |
| `docs/` | Atlas deployment and rollback guide |
| `tools/` | Windows network/NAT helper scripts |
| `.env.atlas.example` | Atlas configuration template without secrets |

The existing `灌溉模型/灌溉模型/` directory contains the fertigation model source. It is retained at its current path for compatibility; treat it as the `fertigation_model` component described above.

## Local Setup

1. Copy `.env.atlas.example` to the Atlas configuration location and supply deployment-specific values.
2. Build the ESP32 firmware:

```powershell
cd esp32_pump_controller
pio run
```

3. Run the public server:

```powershell
python server/zhirun_server.py
```

4. Deploy the Atlas collector with `edge/deploy/zhirun-atlas-collector.service`.

The Atlas configuration must set `ZHIRUN_ATLAS_SERVER` to the public service,
not to a PC-side relay. Verify the runtime route with:

```bash
ip route get 47.92.195.5
curl --interface eth0 -I http://47.92.195.5/
```

Some Atlas images run ConnMan alongside Netplan. If ConnMan manages the
PC-facing `eth1`, disable IPv4 for that ConnMan service so it cannot replace
the router default route. Keep the static Netplan address on `eth1` for local
maintenance, and confirm that `ip route get 47.92.195.5` selects `eth0`.

## Security

Do not commit a real `.env` file, SSH keys, Wi-Fi passwords, device tokens, firmware images, or PlatformIO `.pio` build directories. The `.gitignore` excludes these paths by default.

## Verification

```powershell
cd "灌溉模型/灌溉模型"
python -m pytest tests
```
