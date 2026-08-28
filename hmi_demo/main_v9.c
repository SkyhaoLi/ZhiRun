#include <lvgl/lvgl.h>
#include <arpa/inet.h>
#include <ctype.h>
#include <netdb.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

extern void lv_port_init(int width, int height, int rotation);

#ifndef HMI_SERVER_HOST
#define HMI_SERVER_HOST "8.145.49.45"
#endif
#ifndef HMI_SERVER_PORT
#define HMI_SERVER_PORT 80
#endif

static lv_obj_t *status_label;
static lv_obj_t *metric_labels[13];
static lv_obj_t *source_label;
static lv_obj_t *pump_label;

static int request(const char *method, const char *path, const char *body,
                   char *out, size_t cap) {
    char port[16], message[1024];
    struct addrinfo hints = {0}, *address = NULL;
    snprintf(port, sizeof(port), "%d", HMI_SERVER_PORT);
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    if (getaddrinfo(HMI_SERVER_HOST, port, &hints, &address) != 0) return -1;

    int fd = socket(address->ai_family, address->ai_socktype, address->ai_protocol);
    if (fd < 0) {
        freeaddrinfo(address);
        return -1;
    }
    struct timeval timeout = {.tv_sec = 2, .tv_usec = 0};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    if (connect(fd, address->ai_addr, address->ai_addrlen) != 0) {
        close(fd);
        freeaddrinfo(address);
        return -1;
    }
    freeaddrinfo(address);

    int length = snprintf(
        message, sizeof(message),
        "%s %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n"
        "Content-Type: application/json\r\nContent-Length: %zu\r\n\r\n%s",
        method, path, HMI_SERVER_HOST, body ? strlen(body) : 0, body ? body : "");
    if (length < 0 || (size_t)length >= sizeof(message) ||
        send(fd, message, (size_t)length, 0) < 0) {
        close(fd);
        return -1;
    }

    size_t used = 0;
    while (used + 1 < cap) {
        ssize_t received = recv(fd, out + used, cap - used - 1, 0);
        if (received <= 0) break;
        used += (size_t)received;
    }
    out[used] = 0;
    close(fd);
    if (strstr(out, " 200 ") == NULL && strstr(out, " 202 ") == NULL) return -1;
    char *body_start = strstr(out, "\r\n\r\n");
    if (!body_start) return -1;
    memmove(out, body_start + 4, strlen(body_start + 4) + 1);
    return 0;
}

static const char *json_value(const char *json, const char *key) {
    char pattern[80];
    snprintf(pattern, sizeof(pattern), "\"%s\":", key);
    const char *value = strstr(json, pattern);
    if (!value) return NULL;
    value += strlen(pattern);
    while (isspace((unsigned char)*value)) value++;
    return value;
}

static bool json_number(const char *json, const char *key, double *number) {
    const char *value = json_value(json, key);
    if (!value || strncmp(value, "null", 4) == 0) return false;
    char *end = NULL;
    *number = strtod(value, &end);
    return end != value;
}

static bool json_boolean(const char *json, const char *key, bool *result) {
    const char *value = json_value(json, key);
    if (!value) return false;
    if (strncmp(value, "true", 4) == 0) {
        *result = true;
        return true;
    }
    if (strncmp(value, "false", 5) == 0) {
        *result = false;
        return true;
    }
    return false;
}

static bool json_string(const char *json, const char *key, char *out, size_t cap) {
    const char *value = json_value(json, key);
    if (!value || *value != '"') return false;
    value++;
    const char *end = strchr(value, '"');
    if (!end) return false;
    size_t length = (size_t)(end - value);
    if (length >= cap) length = cap - 1;
    memcpy(out, value, length);
    out[length] = 0;
    return true;
}

static void set_metric(unsigned index, bool available, double value,
                       unsigned precision, const char *unit) {
    char text[48];
    if (available) {
        snprintf(text, sizeof(text), precision == 0 ? "%.0f %s" :
                 precision == 2 ? "%.2f %s" : "%.1f %s", value, unit);
        lv_label_set_text(metric_labels[index], text);
    } else {
        lv_label_set_text(metric_labels[index], "--");
    }
}

static void refresh(lv_timer_t *timer) {
    (void)timer;
    fprintf(stderr, "HMI_REFRESH begin\n");
    char response[4096], device[64] = "unknown", source[32] = "unknown";
    double values[13] = {0}, age;

    if (request("GET", "/data", NULL, response, sizeof(response)) != 0) {
        fprintf(stderr, "HMI_REFRESH data_request_failed\n");
        lv_label_set_text(status_label, "Server offline");
        for (unsigned index = 0; index < 13; index++) lv_label_set_text(metric_labels[index], "--");
        lv_label_set_text(source_label, "Check Ethernet or Wi-Fi connection");
        return;
    }
    fprintf(stderr, "HMI_REFRESH data_received\n");

    static const char *keys[] = {
        "airTemp", "airHum", "co2", "lux", "soilMoist", "soilTemp",
        "soilPH", "soilEc", "n", "p", "k", "windSpeed", "rainMm"
    };
    static const char *units[] = {
        "C", "%", "ppm", "lux", "%", "C", "", "dS/m",
        "mg/kg", "mg/kg", "mg/kg", "m/s", "mm"
    };
    static const unsigned precision[] = {1, 1, 0, 0, 1, 1, 2, 2, 0, 0, 0, 1, 1};
    bool available[13];
    for (unsigned index = 0; index < 13; index++) {
        available[index] = json_number(response, keys[index], &values[index]);
        set_metric(index, available[index], values[index], precision[index], units[index]);
    }
    bool has_age = json_number(response, "_age", &age);
    json_string(response, "_device_id", device, sizeof(device));
    json_string(response, "_source", source, sizeof(source));
    fprintf(stderr, "HMI_REFRESH metrics_updated\n");

    bool live = strcmp(source, "rk3506") == 0 && (!has_age || age < 30.0);
    lv_label_set_text(status_label, live ? "RK3506 live" : "Server data stale");
    char source_text[180];
    if (has_age)
        snprintf(source_text, sizeof(source_text), "Device: %s | Source: %s | Age: %.0f s", device, source, age);
    else
        snprintf(source_text, sizeof(source_text), "Device: %s | Source: %s", device, source);
    lv_label_set_text(source_label, source_text);
    fprintf(stderr, "HMI_REFRESH source_updated\n");

    if (request("GET", "/valve/config", NULL, response, sizeof(response)) == 0) {
        bool online = false, pump_on = false;
        json_boolean(response, "online", &online);
        if (!online) lv_label_set_text(pump_label, "Offline");
        else {
            json_boolean(response, "valveOn", &pump_on);
            lv_label_set_text(pump_label, pump_on ? "Pump: ON" : "Pump: OFF");
        }
    }
    fprintf(stderr, "HMI_REFRESH complete\n");
}

static void stop_pump(lv_event_t *event) {
    (void)event;
    char response[1024];
    if (request("POST", "/valve/manual", "{\"action\":\"close\"}", response, sizeof(response)) == 0)
        lv_label_set_text(pump_label, "STOP queued");
    else
        lv_label_set_text(pump_label, "Command failed");
}

static lv_obj_t *make_panel(lv_obj_t *parent, int x, int y, int width, int height) {
    lv_obj_t *panel = lv_obj_create(parent);
    lv_obj_set_pos(panel, x, y);
    lv_obj_set_size(panel, width, height);
    lv_obj_set_style_radius(panel, 6, 0);
    lv_obj_set_style_bg_color(panel, lv_color_hex(0x141D29), 0);
    lv_obj_set_style_border_color(panel, lv_color_hex(0x2A3A4F), 0);
    lv_obj_set_style_pad_all(panel, 9, 0);
    lv_obj_clear_flag(panel, LV_OBJ_FLAG_SCROLLABLE);
    return panel;
}

int main(void) {
    lv_port_init(0, 0, 0);
    lv_obj_t *screen = lv_scr_act();
    lv_obj_set_style_bg_color(screen, lv_color_hex(0x0B1017), 0);

    lv_obj_t *title = lv_label_create(screen);
    lv_label_set_text(title, "ZhiRun fertigation monitor");
    lv_obj_set_style_text_color(title, lv_color_hex(0xE8EDF5), 0);
    lv_obj_set_pos(title, 18, 15);

    status_label = lv_label_create(screen);
    lv_label_set_text(status_label, "Starting");
    lv_obj_set_style_text_color(status_label, lv_color_hex(0x58D3AE), 0);
    lv_obj_align(status_label, LV_ALIGN_TOP_RIGHT, -18, 16);

    static const char *names[] = {
        "Air temperature", "Air humidity", "CO2", "Light", "Soil moisture",
        "Soil temperature", "Soil pH", "Soil EC", "Nitrogen (N)",
        "Phosphorus (P)", "Potassium (K)", "Wind speed", "Rainfall"
    };
    for (unsigned index = 0; index < 13; index++) {
        int column = (int)(index % 5);
        int row = (int)(index / 5);
        lv_obj_t *panel = make_panel(screen, 18 + column * 153, 50 + row * 109, 145, 101);
        lv_obj_t *name = lv_label_create(panel);
        lv_label_set_text(name, names[index]);
        lv_obj_set_style_text_color(name, lv_color_hex(0x91A3BA), 0);
        metric_labels[index] = lv_label_create(panel);
        lv_label_set_text(metric_labels[index], "--");
        lv_obj_set_style_text_color(metric_labels[index], lv_color_hex(0xF1F5FA), 0);
        lv_obj_align(metric_labels[index], LV_ALIGN_BOTTOM_LEFT, 0, -2);
    }

    lv_obj_t *control_panel = make_panel(screen, 477, 268, 145, 101);
    lv_obj_t *control_title = lv_label_create(control_panel);
    lv_label_set_text(control_title, "Pump status");
    lv_obj_set_style_text_color(control_title, lv_color_hex(0x58D3AE), 0);
    pump_label = lv_label_create(control_panel);
    lv_label_set_text(pump_label, "State unknown");
    lv_obj_set_width(pump_label, 125);
    lv_obj_set_pos(pump_label, 0, 27);

    lv_obj_t *action_panel = make_panel(screen, 630, 268, 145, 101);
    lv_obj_t *button = lv_btn_create(action_panel);
    lv_obj_set_size(button, 125, 70);
    lv_obj_align(button, LV_ALIGN_BOTTOM_MID, 0, 0);
    lv_obj_add_event_cb(button, stop_pump, LV_EVENT_CLICKED, NULL);
    lv_obj_t *button_label = lv_label_create(button);
    lv_label_set_text(button_label, "STOP PUMP");
    lv_obj_center(button_label);

    source_label = lv_label_create(screen);
    lv_label_set_text(source_label, "Waiting for server");
    lv_obj_set_width(source_label, 760);
    lv_obj_set_style_text_color(source_label, lv_color_hex(0x8293A8), 0);
    lv_obj_set_pos(source_label, 18, 445);

    lv_timer_create(refresh, 5000, NULL);
    while (1) {
        lv_timer_handler();
        usleep(5000);
    }
    return 0;
}
