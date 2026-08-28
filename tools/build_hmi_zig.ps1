$ErrorActionPreference = 'Stop'

$project = Split-Path -Parent $PSScriptRoot
$zig = Get-ChildItem "$project/downloads/zig-full-unpack" -Recurse -Filter zig.exe |
    Select-Object -First 1
if (-not $zig) {
    throw 'Zig was not found under downloads/zig-full-unpack.'
}

$demo = "$project/vendor_lvgl_demo/lvgl_ui_demo"
$sysroot = "$project/toolchain/gcc-arm-10.3-2021.07-x86_64-arm-none-linux-gnueabihf/host/arm-buildroot-linux-gnueabihf/sysroot"
$sources = @(
    "$project/hmi_demo/main_v9.c"
    "$demo/lvgl9/evdev.c"
    "$demo/lvgl9/lv_port_disp.c"
    "$demo/lvgl9/lv_port_indev.c"
    "$demo/lvgl9/lv_port_init.c"
    "$demo/lvgl9/src/drivers/display/rkadk/rkadk.c"
)
$libraries = @(
    "$sysroot/usr/lib/liblvgl.so"
    "$sysroot/usr/lib/librkadk.so"
    "$sysroot/usr/lib/librockit.so"
    "$sysroot/usr/lib/librga.so.2.1.0"
    "$sysroot/usr/lib/libevdev.so.2.3.0"
    "$sysroot/usr/lib/libdrm.so.2.4.0"
    "$sysroot/usr/lib/libfreetype.so.6.20.1"
)
$includes = @(
    $demo
    "$demo/lvgl9"
    "$sysroot/usr/include"
    "$sysroot/usr/include/lvgl"
    "$sysroot/usr/include/lvgl/lv_drivers"
    "$sysroot/usr/include/rkadk"
    "$sysroot/usr/include/lvgl/src/drivers/display/rkadk"
    "$demo/lvgl9/src/drivers/display/rkadk"
    "$sysroot/usr/include/rockchip"
    "$sysroot/usr/include/libdrm"
)

$arguments = @(
    'cc', '-target', 'arm-linux-gnueabihf', '-mcpu=cortex_a7', '--sysroot', $sysroot
    '-D__EXPORTED_HEADERS__', '-DUSE_RKADK=1', '-DUSE_EVDEV=1', '-DLVGL_V9=1', '-DLV_USE_RKADK=1'
)
foreach ($include in $includes) { $arguments += @('-I', $include) }
$arguments += @('-w', '-O2') + $sources + @('-Wl,--no-as-needed') + $libraries
$arguments += @(
    '-lpthread', '-lm', '-ldl', '-Wl,--gc-sections', '-Wl,--allow-shlib-undefined'
    '-Wl,--disable-new-dtags', '-Wl,-rpath,/oem/usr/lib', '-o', "$project/downloads/zhirun_hmi_demo"
)

& $zig.FullName @arguments
if ($LASTEXITCODE -ne 0) { throw "HMI build failed with exit code $LASTEXITCODE." }
Get-Item "$project/downloads/zhirun_hmi_demo" | Select-Object FullName, Length, LastWriteTime
