import io
import os
import paramiko
from PIL import Image, ImageDraw, ImageFont

HOST = "192.168.1.10"
USER = "root"
PASSWORD = "root"

def font(size):
    for path in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/arial.ttf"):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

def main():
    image = Image.new("RGB", (800, 480), "#0b1017")
    draw = ImageDraw.Draw(image)
    title = font(28); body = font(20); small = font(16)
    draw.text((22, 18), "ZhiRun fertigation monitor", fill="#e6ebf5", font=title)
    draw.text((620, 26), "Server online", fill="#53c7a7", font=small)
    metrics = [("Air temperature", "-- C", "#e6ebf5"), ("Air humidity", "-- %", "#9fb6d6"),
               ("Soil moisture", "-- %", "#53c7a7"), ("Soil EC", "-- dS/m", "#77aaf7")]
    for i, (label, value, color) in enumerate(metrics):
        x = 18 + i * 192
        draw.rounded_rectangle((x, 70, x + 180, 168), radius=8, fill="#172536", outline="#2a4a53")
        draw.text((x + 12, 84), label, fill="#9fb2cc", font=small)
        draw.text((x + 12, 124), value, fill=color, font=body)
    draw.rounded_rectangle((18, 190, 500, 360), radius=8, fill="#131a27", outline="#223047")
    draw.text((32, 208), "Server model recommendation", fill="#9fb2cc", font=small)
    draw.text((32, 254), "Water -- m3/mu", fill="#53c7a7", font=body)
    draw.text((32, 300), "N --   P --   K -- kg/mu", fill="#e6ebf5", font=body)
    draw.rounded_rectangle((520, 190, 782, 360), radius=8, fill="#143026", outline="#2f6a58")
    draw.text((536, 210), "Irrigation pump OFF", fill="#e6ebf5", font=body)
    draw.rounded_rectangle((536, 260, 766, 320), radius=8, fill="#236b55")
    draw.text((580, 279), "Toggle irrigation", fill="#ffffff", font=small)
    draw.text((22, 426), "Touchscreen HMI | RK3506", fill="#9fb6d6", font=small)
    raw = io.BytesIO(); image.save(raw, format="BMP"); bmp = raw.getvalue()
    # 24-bit BMP is converted on the board by a tiny Python script if PIL exists.
    client = paramiko.SSHClient(); client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=10)
    sftp = client.open_sftp(); sftp.putfo(io.BytesIO(bmp), "/tmp/zhirun_hmi.bmp"); sftp.close()
    command = "python3 -c 'from PIL import Image; im=Image.open(\"/tmp/zhirun_hmi.bmp\").convert(\"RGB\"); raw=im.tobytes(); open(\"/tmp/zhirun_rgb\",\"wb\").write(raw)'"
    _, out, err = client.exec_command(command); print(out.read().decode(), err.read().decode())
    client.close()

if __name__ == "__main__":
    main()
