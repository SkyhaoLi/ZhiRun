import os
import paramiko

HOST = "8.145.49.45"
PASSWORD = os.environ["ZHIRUN_BUILD_PASSWORD"]
ROOT = "/tmp/zhirun-hmi-build/vendor_lvgl_demo/lvgl_ui_demo"
TOOL = "/opt/rk3506-toolchain/gcc-arm-10.3-2021.07-x86_64-arm-none-linux-gnueabihf/host"

def run(c, command, timeout=600):
    print("$", command)
    ch, out, err = c.exec_command(command, timeout=timeout)
    stdout, stderr = out.read().decode(errors="replace"), err.read().decode(errors="replace")
    print(stdout)
    if stderr:
        print(stderr)
    return out.channel.recv_exit_status()

def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=15,
              look_for_keys=False, allow_agent=False)
    s = c.open_sftp()
    local_main = os.path.join(os.path.dirname(__file__), "..", "hmi_demo", "main_v9.c")
    s.put(local_main, ROOT + "/main.c")
    local_rkadk = os.path.join(
        os.path.dirname(__file__), "..", "vendor_lvgl_demo", "lvgl_ui_demo", "lvgl9",
        "src", "drivers", "display", "rkadk", "rkadk.c",
    )
    s.put(local_rkadk, ROOT + "/lvgl9/src/drivers/display/rkadk/rkadk.c")
    s.close()
    run(c, "sed -i 's#^set(TOOLCHAIN_DIR.*#set(TOOLCHAIN_DIR \"%s/bin\")#; s#^set(CMAKE_SYSROOT.*#set(CMAKE_SYSROOT \"%s/arm-buildroot-linux-gnueabihf/sysroot\")#' %s/toolchain-arm.cmake" % (TOOL, TOOL, ROOT))
    code = run(c, "cd %s && sed -i 's#arm-none-linux-gnueabihf-gcc#arm-buildroot-linux-gnueabihf-gcc#; s#arm-none-linux-gnueabihf-g++#arm-buildroot-linux-gnueabihf-g++#' toolchain-arm.cmake && rm -rf build && cmake -DCMAKE_TOOLCHAIN_FILE=./toolchain-arm.cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_EXE_LINKER_FLAGS='-Wl,-rpath,/oem/usr/lib' -S . -B build && cmake --build build -j4 && file build/lvgl_ui_demo" % ROOT)
    if code == 0:
        s = c.open_sftp()
        s.get(ROOT + "/build/lvgl_ui_demo", os.path.join(os.path.dirname(__file__), "..", "downloads", "zhirun_hmi_demo"))
        s.get(TOOL + "/arm-buildroot-linux-gnueabihf/sysroot/usr/lib/liblvgl.so", os.path.join(os.path.dirname(__file__), "..", "downloads", "liblvgl.so"))
        s.close()
        print("BUILD_OK")
    else:
        print("BUILD_FAILED", code)
    c.close()

if __name__ == "__main__":
    main()
