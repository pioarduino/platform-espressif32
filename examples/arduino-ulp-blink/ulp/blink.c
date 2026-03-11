/*
 * SPDX-FileCopyrightText: 2024 Espressif Systems (Shanghai) CO LTD
 * SPDX-License-Identifier: Unlicense OR CC0-1.0
 */

#include <stdint.h>
#include <stdbool.h>
#include "ulp_lp_core_utils.h"
#include "ulp_lp_core_gpio.h"

#define BLINK_PIN LP_IO_NUM_3
#define BLINK_DELAY_MS 1000

volatile bool ulp_led_state;

int main(void)
{
    ulp_lp_core_gpio_init(BLINK_PIN);
    ulp_lp_core_gpio_output_enable(BLINK_PIN);

    ulp_led_state = !ulp_led_state;
    ulp_lp_core_gpio_set_level(BLINK_PIN, (int)ulp_led_state);

    ulp_lp_core_delay_us(BLINK_DELAY_MS * 1000);

    return 0;
}
