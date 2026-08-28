# toolchain-arm.cmake
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR arm)

# 指定交叉编译工具链路径
set(TOOLCHAIN_DIR "/work/bsp/rk3506_hmi_sdk/rk3506_linux6.1_sdk_v1.2.0/prebuilts/gcc/linux-x86/arm/gcc-arm-10.3-2021.07-x86_64-arm-none-linux-gnueabihf/bin")
set(CMAKE_C_COMPILER ${TOOLCHAIN_DIR}/arm-none-linux-gnueabihf-gcc)
set(CMAKE_CXX_COMPILER ${TOOLCHAIN_DIR}/arm-none-linux-gnueabihf-g++)

# 指定sysroot
set(CMAKE_SYSROOT "/work/bsp/rk3506_hmi_sdk/rk3506_linux6.1_sdk_v1.2.0/buildroot/output/rockchip_hd_rk3506g_hmi_nand/host/arm-buildroot-linux-gnueabihf/sysroot")

# 设置查找规则（只在sysroot中查找库和头文件）
set(CMAKE_FIND_ROOT_PATH ${CMAKE_SYSROOT})
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
