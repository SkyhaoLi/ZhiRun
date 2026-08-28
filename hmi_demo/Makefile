APP ?= zhirun_hmi_demo
CC ?= arm-buildroot-linux-gnueabihf-gcc
SYSROOT ?=
LVGL_PREFIX ?=$(SYSROOT)/usr
CFLAGS += -O2 -Wall -Wextra -std=c11 -D_DEFAULT_SOURCE -DUSE_RKADK=1 -DUSE_EVDEV=1 -DLVGL_V9=1
CFLAGS += -I$(LVGL_PREFIX)/include -I$(LVGL_PREFIX)/include/lvgl -I../vendor_lvgl_demo/lvgl_ui_demo/lvgl9
LDFLAGS += --sysroot=$(SYSROOT) -L$(LVGL_PREFIX)/lib -Wl,-rpath,/usr/lib
LDLIBS += -llvgl -llv_drivers -lrkadk -lrockit -lrga -ldrm -levdev -lpthread -lm -ldl
PORT_SRCS = ../vendor_lvgl_demo/lvgl_ui_demo/lvgl9/lv_port_init.c \
            ../vendor_lvgl_demo/lvgl_ui_demo/lvgl9/lv_port_disp.c \
            ../vendor_lvgl_demo/lvgl_ui_demo/lvgl9/lv_port_indev.c \
            ../vendor_lvgl_demo/lvgl_ui_demo/lvgl9/evdev.c \
            ../vendor_lvgl_demo/lvgl_ui_demo/lvgl9/src/drivers/display/rkadk/rkadk.c

all: $(APP)

$(APP): main_v9.c $(PORT_SRCS)
	$(CC) $(CFLAGS) $(CPPFLAGS) $(LDFLAGS) -o $@ $^ $(LDLIBS)

clean:
	rm -f $(APP)

.PHONY: all clean
