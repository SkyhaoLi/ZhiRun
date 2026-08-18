# Atlas 200I DK A2 采集部署

## 范围

Atlas 200I DK A2 通过一个 USB-RS485 适配器采集土壤、百叶盒和风速数据，并通过 GPIO16 统计雨量翻斗脉冲。采集器每 2 秒向服务器 `/push` 上报，网页从 `/data` 获取实时数据。

## 传感器配置

| 数据 | 地址 | 波特率 | 寄存器 | 换算 |
|---|---:|---:|---:|---|
| 百叶盒温度、湿度 | 1 | 4800 | 0-1 | 除以 10 |
| 土壤水分、温度、pH、N、P、K | 2 | 4800 | 0-6 | 水分、温度、pH 除以 10 |
| CO2 | 3 | 4800 | 0 | ppm 直读 |
| 风速 | 4 | 4800 | 0 | 除以 10 m/s |
| 光照 | 5 | 4800 | 1 | lux 直读 |

雨量模块接线：`VCC -> 3.3V`，`GND -> GND`，`DO -> Atlas GPIO16`。每个翻斗脉冲默认累计 `0.3 mm`。采集器只在确认配置方向的 GPIO 电平边沿后计数，并默认使用 300 ms 去抖，避免触点抖动或线路毛刺产生虚假雨量；可通过 `ZHIRUN_RAIN_DEBOUNCE_MS` 调整。

## 文件

| 文件 | 用途 |
|---|---|
| `edge/atlas200i_collector.py` | RS485 轮询、GPIO 雨量计数和上报 |
| `.env.atlas.example` | Atlas 配置模板 |
| `edge/deploy/zhirun-atlas-collector.service` | systemd 服务模板 |
| `server/zhirun_server.py` | Atlas 实时数据服务 |
| `server/index.html` | 实时展示页面 |

## 部署

1. 在 Atlas 上将 `.env.atlas.example` 复制为 `/home/HwHiAiUser/.config/zhirun-atlas.env`，填写服务器地址和访问令牌。
2. 通过 `ls -l /dev/serial/by-id/` 确认 USB-RS485 的稳定设备路径，并写入 `ZHIRUN_RS485_PORT`。
3. 使用 root systemd 服务运行采集器。GPIO sysfs 的输入和边沿配置需要该权限。
4. 执行一次验证：

```bash
python3 /home/HwHiAiUser/zhirun/edge/atlas200i_collector.py \
  --config /home/HwHiAiUser/.config/zhirun-atlas.env --once
```

## 路由器 Wi-Fi 配网

联网页会通过采集服务向 Atlas 下发扫描和连接命令。Atlas 上需要已经接入并加载无线网卡驱动，且系统安装、启用 `NetworkManager`（`nmcli`）。进入联网页后点击“扫描”，选择路由器 Wi-Fi 并输入密码即可连接；密码只存在于一次待执行命令中，不会写入网页服务的状态文件或日志。

可先在 Atlas 上确认无线环境：

```bash
nmcli device status
nmcli device wifi list
```

若没有显示 `wifi` 类型设备，先安装并加载 USB Wi-Fi 驱动。项目中的 AIC8800 驱动支持通过 `nmcli` 管理。

## 水泵手动控制

`GPIO16` 已保留给雨量翻斗，不能接水泵。当前水泵 MOS 驱动板的 `PWM/IN`
接在物理 15 脚（板级标注 `GPIO22`，SoC 信号 `GPIO2_15`）。在 Linux
sysfs 中该信号的全局 GPIO line 是 `79`，配置为：

```ini
ZHIRUN_VALVE_GPIO=79
ZHIRUN_VALVE_ACTIVE_HIGH=1
ZHIRUN_VALVE_MAX_RUN_S=180
```

采集器会每秒轮询一次阀门指令、把执行结果回报到网页，并在达到最长运行时间、
采集器退出或 GPIO 配置为空时保持关阀。若驱动板是低电平有效，将
`ZHIRUN_VALVE_ACTIVE_HIGH` 改为 `0`。

## 验收

1. `systemctl is-active zhirun-atlas-collector.service` 返回 `active`。
2. 公网 `/data` 的 `_age` 不大于 2 秒，`_frameSeq` 持续递增。
3. `rainTips` 和 `rainMm` 为数值；翻动一次雨量翻斗后，`rainMm` 增加 `0.3`。
4. 页面右上和底部均依据 `_age` 显示相同的在线状态。
