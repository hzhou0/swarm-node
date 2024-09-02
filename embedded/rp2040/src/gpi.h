#pragma once

#include "io.h"
#include "pico/stdlib.h"

typedef struct gpi {
  bool charged1, charged2, charged3, charged4, in_conn;
} GPIState;

const struct GPIPinMap {
  uint8_t not_charged1, not_charged2, not_charged3, not_charged4, not_in_conn;
} GPIPinMap = {13, 11, 10, 14, 25};

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

static inline void gpi_enable_alert() {
  const uint32_t event_mask = GPIO_IRQ_EDGE_RISE | GPIO_IRQ_EDGE_FALL;
  gpio_set_irq_enabled(GPIPinMap.not_charged1, event_mask, true);
  gpio_set_irq_enabled(GPIPinMap.not_charged2, event_mask, true);
  gpio_set_irq_enabled(GPIPinMap.not_charged3, event_mask, true);
  gpio_set_irq_enabled(GPIPinMap.not_charged4, event_mask, true);
  gpio_set_irq_enabled(GPIPinMap.not_in_conn, event_mask, true);
}

static inline void gpi_alert_irq_handler(uint pin, GPIState *gpi) {
  log_debug("gpi_alert_irq_handler");
  if (pin == GPIPinMap.not_charged1)
    gpi->charged1 = !gpio_get(GPIPinMap.not_charged1);
  else if (pin == GPIPinMap.not_charged2)
    gpi->charged2 = !gpio_get(GPIPinMap.not_charged2);
  else if (pin == GPIPinMap.not_charged3)
    gpi->charged3 = !gpio_get(GPIPinMap.not_charged3);
  else if (pin == GPIPinMap.not_charged4)
    gpi->charged4 = !gpio_get(GPIPinMap.not_charged4);
  else if (pin == GPIPinMap.not_in_conn)
    gpi->in_conn = !gpio_get(GPIPinMap.not_in_conn);
}

static inline void emit_gpi_state(const GPIState *gpi) {
  const uint8_t stateBuf[5] = {
      gpi->charged1, gpi->charged2, gpi->charged3, gpi->charged4, gpi->in_conn,
  };
  emit(EVENT_GPI_STATE, stateBuf, 5);
}