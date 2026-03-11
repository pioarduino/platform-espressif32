#include <Arduino.h>
#include "ulp_lp_core.h"
#include "ulp_main.h"
#include "esp_err.h"

extern const uint8_t ulp_main_bin_start[] asm("_binary_ulp_main_bin_start");
extern const uint8_t ulp_main_bin_end[]   asm("_binary_ulp_main_bin_end");

void start_ulp_program() {
    ESP_ERROR_CHECK(ulp_lp_core_load_binary(ulp_main_bin_start,
                                            (ulp_main_bin_end - ulp_main_bin_start)));

    ulp_lp_core_cfg_t cfg = {
        .wakeup_source = ULP_LP_CORE_WAKEUP_SOURCE_LP_TIMER,
        .lp_timer_sleep_duration_us = 1000000,
    };

    ESP_ERROR_CHECK(ulp_lp_core_run(&cfg));
}

void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println("Starting ULP blink program...");
    Serial.printf("ULP binary size: %lu bytes\n",
                  (unsigned long)(ulp_main_bin_end - ulp_main_bin_start));
    start_ulp_program();
    Serial.println("ULP program running — LED on GPIO3 should blink");
}

void loop() {
    Serial.printf("ULP led_state: %d\n", (int)ulp_ulp_led_state);
    delay(2000);
}
