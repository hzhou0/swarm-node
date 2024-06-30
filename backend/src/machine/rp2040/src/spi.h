#pragma once
#include "hardware/spi.h"
#include "pico/stdlib.h"

#define SPI_1MHZ (1000 * 1000)

typedef struct SPIBus {
  struct spi_inst *inst;
  uint8_t sck_pin;
  uint8_t tx_pin;
  uint8_t rx_pin;
  uint8_t csn_pin;
};

static inline void spi_bus_select(SPIBus spi_bus) {
  asm volatile("nop \n nop \n nop");
  gpio_put(spi_bus.csn_pin, false);  // Active low
  asm volatile("nop \n nop \n nop");
}

static inline void spi_bus_deselect(SPIBus spi_bus) {
  asm volatile("nop \n nop \n nop");
  gpio_put(spi_bus.csn_pin, true);
  asm volatile("nop \n nop \n nop");
}

static inline SPIBus spi_bus(struct spi_inst *inst, uint8_t sck_pin,
                             uint8_t tx_pin, uint8_t rx_pin, uint8_t csn_pin) {
  spi_init(inst, SPI_1MHZ);
  gpio_set_function(sck_pin, GPIO_FUNC_SPI);
  gpio_set_function(tx_pin, GPIO_FUNC_SPI);
  gpio_set_function(rx_pin, GPIO_FUNC_SPI);

  gpio_init(csn_pin);
  gpio_set_dir(csn_pin, GPIO_OUT);
  gpio_put(csn_pin, true);
  return (SPIBus){inst, sck_pin, tx_pin, rx_pin, csn_pin};
}

typedef struct MPU6500 {
  SPIBus spi_bus;
  uint8_t fsync_pin;
  uint8_t int_pin;
};