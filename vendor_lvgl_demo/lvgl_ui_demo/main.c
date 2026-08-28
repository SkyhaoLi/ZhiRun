/*
 * Copyright (c) 2021 Rockchip, Inc. All Rights Reserved.
 *
 *  Licensed under the Apache License, Version 2.0 (the "License");
 *  you may not use this file except in compliance with the License.
 *  You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing, software
 *  distributed under the License is distributed on an "AS IS" BASIS,
 *  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *  See the License for the specific language governing permissions and
 *  limitations under the License.
 */

#include <lvgl/lvgl.h>
#include <lvgl/lv_conf.h>

#include <unistd.h>
#include <pthread.h>
#include <time.h>
#include <stdio.h>
#include <stdlib.h>

#include "main.h"
#include "lv_port_init.h"


static int quit = 0;

static void signal_handler(int sig)
{
    fprintf(stderr, "signal %d\n", sig);
    quit = 1;
}

int main(int argc, char **argv)
{
    printf("lvgl_demo - LVGL v9 Hello World Demo\n");
    printf("Platform: Rockchip RK3506\n");
    

    signal(SIGINT, signal_handler);

    lv_port_init(0, 0, 0);

    // 获取当前屏幕
    lv_obj_t *scr = lv_scr_act();
    
    // 设置屏幕背景为黑色
    lv_obj_set_style_bg_color(scr, lv_color_black(), 0);
    
    // 创建标签控件
    lv_obj_t *label = lv_label_create(scr);
    
    // 设置标签文本
    lv_label_set_text(label, "Hello World!");
    
    // 设置文本为白色
    lv_obj_set_style_text_color(label, lv_color_white(), 0);
    
    // 设置大字体（如果可用）
    const lv_font_t *font = &lv_font_montserrat_48;
    lv_obj_set_style_text_font(label, font, 0);
    
    // 让标签在屏幕中央显示
    lv_obj_center(label);
        
    printf("UI created, entering main loop...\n");

    while (!quit)
    {
        lv_task_handler();
        usleep(1000);
    }

    return 0;
}
