#pragma once

#include "pico/stdlib.h"

typedef struct GPI {
  bool charged1, charged2, charged3, charged4, in_conn;
} GPI;

const struct GPIPinMap {
  uint8_t not_charged1, not_charged2, not_charged3, not_charged4, not_in_conn;
} GPIPinMap = {
	13, 11, 10, 14, 25
};

static inline void high_impedance_pin_init(uint pin) {
  gpio_init(pin);
  gpio_set_dir(pin, GPIO_IN);
  gpio_pull_up(pin);
  // Set a weak pull up
  gpio_set_drive_strength(pin, GPIO_DRIVE_STRENGTH_2MA);
}

static inline void gpi_init() {
  high_impedance_pin_init(GPIPinMap.not_charged1);
  high_impedance_pin_init(GPIPinMap.not_charged2);
  high_impedance_pin_init(GPIPinMap.not_charged3);
  high_impedance_pin_init(GPIPinMap.not_charged4);
  high_impedance_pin_init(GPIPinMap.not_in_conn);
}

static inline GPI gpi_get() {
  return (GPI){
	  !gpio_get(GPIPinMap.not_charged1),
	  !gpio_get(GPIPinMap.not_charged2),
	  !gpio_get(GPIPinMap.not_charged3),
	  !gpio_get(GPIPinMap.not_charged4),
	  !gpio_get(GPIPinMap.not_in_conn),
  };
}