/**
 * @file lv_port_indev.c
 *
 */

#include <stdlib.h>
#include <lvgl.h>
#include "evdev.h"

static lv_indev_t *indev_touchpad = NULL;
static lv_indev_t *indev_sdl = NULL;

#if defined(USE_SENSOR) && USE_SENSOR
static lv_indev_t *lsensor = NULL;
static lv_indev_t *psensor = NULL;

lv_indev_t *lv_port_indev_get_lsensor(void)
{
    return lsensor;
}

lv_indev_t *lv_port_indev_get_psensor(void)
{
    return psensor;
}
#endif

void lv_port_indev_init(int rot)
{
    lv_disp_t *disp;

    disp = lv_display_get_default();
    if (evdev_init(disp, rot) == 0)
    {
        indev_touchpad = lv_indev_create();
        lv_indev_set_type(indev_touchpad, LV_INDEV_TYPE_POINTER);
        lv_indev_set_read_cb(indev_touchpad, evdev_read);
    }

}

