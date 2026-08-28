cmake_minimum_required(VERSION 3.8)

project(lvgl_ui_demo)

add_definitions(
    -g 
    -D__EXPORTED_HEADERS__
    -DUSE_RKADK=1 
    -DUSE_EVDEV=1
    -DLVGL_V9=1
    -DLV_USE_RKADK=1
)

# 收集源文件，只包括项目源代码目录下的文件，不包括构建目录
file(GLOB ROOT_SOURCES "*.c")
file(GLOB LVGL9_SOURCES "lvgl9/*.c")
file(GLOB RKADK_SOURCES
    "lvgl9/src/drivers/display/rkadk/*.c")
set(SRCS ${ROOT_SOURCES} ${LVGL9_SOURCES} ${RKADK_SOURCES})

# 创建可执行文件
add_executable(${PROJECT_NAME} ${SRCS})

include_directories(
	${PROJECT_SOURCE_DIR}/
    ${PROJECT_SOURCE_DIR}/lvgl9/
    ${CMAKE_SYSROOT}/usr/include/
    ${CMAKE_SYSROOT}/usr/include/rkadk/
    ${CMAKE_SYSROOT}/usr/include/lvgl/lv_drivers/rkadk/
    ${CMAKE_SYSROOT}/usr/include/lvgl/src/drivers/display/rkadk/
    ${PROJECT_SOURCE_DIR}/lvgl9/src/drivers/display/rkadk/
	${CMAKE_SYSROOT}/usr/include/lvgl/
	${CMAKE_SYSROOT}/usr/include/lvgl/lv_drivers/
	${CMAKE_SYSROOT}/usr/include/rockchip/
	${CMAKE_SYSROOT}/usr/include/libdrm
    	${CMAKE_SYSROOT}/usr/include/drm
    	${CMAKE_SYSROOT}/usr/include/rockchip
	)

# 在链接库之前，先查找lvgl库的位置
find_library(LVGL_LIB lvgl PATHS ${CMAKE_SYSROOT}/usr/lib REQUIRED)
message(STATUS "Found LVGL library: ${LVGL_LIB}")
# 然后链接这个库
target_link_libraries(${PROJECT_NAME} PRIVATE
    ${LVGL_LIB}
    rkadk
    rockit
    rga
    evdev
    drm
    freetype
    pthread
    m
    dl
)

# 添加编译选项
target_compile_options(${PROJECT_NAME} PRIVATE
    -Wall
    -Wextra
    -O2
)

# 如果是交叉编译，可以添加链接选项
if(CMAKE_CROSSCOMPILING)
    target_link_options(${PROJECT_NAME} PRIVATE
        -Wl,--gc-sections
#-Wl,--as-needed
    )
endif()

