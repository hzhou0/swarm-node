#pragma once

#include "hardware/i2c.h"
#include "io.h"
#include "pico/stdlib.h"

#define I2C_SPEED_STD (100 * 1000)
#define I2C_SPEED_FAST (400 * 1000)

typedef struct I2CBus {
  struct i2c_inst *inst;
  uint8_t scl_pin;
  uint8_t sda_pin;
} I2CBus;

static inline I2CBus i2c_bus(struct i2c_inst *inst, uint8_t scl_pin, uint8_t sda_pin,
                             uint i2c_speed) {
  i2c_init(inst, i2c_speed);
  gpio_set_function(scl_pin, GPIO_FUNC_I2C);
  gpio_set_function(sda_pin, GPIO_FUNC_I2C);
  gpio_pull_up(scl_pin);
  gpio_pull_up(sda_pin);
  return (I2CBus){inst, scl_pin, sda_pin};
}

#define INA226_BUS_VOLTAGE_LSB_UV 1250u
#define INA226_SHUNT_VOLTAGE_LSB_NV 2500u
typedef struct INA226 {
  I2CBus i2c_bus;
  uint8_t i2c_address;
  uint8_t alert_pin;
  uint current_lsb_ua;
  uint power_lsb_uw;
  uint32_t irq_event_mask;
} INA226;

static inline void ina226_calibrate(INA226 *ina226, uint max_current_uA, uint resistance_uohm);

static inline INA226 ina226(I2CBus i2c_bus, uint8_t i2c_address, uint8_t current_alert_pin,
                            uint max_current_uA, uint resistance_uohm) {
  INA226 ina = {i2c_bus, i2c_address, current_alert_pin, 0, 0};
  gpio_init(current_alert_pin);
  gpio_set_dir(current_alert_pin, GPIO_IN);
  ina226_calibrate(&ina, max_current_uA, resistance_uohm);
  return ina;
}

typedef enum INA226_REG {
  INA226_REG_CONFIGURATION = 0x00,
  INA226_REG_SHUNT_VOLTAGE = 0x01,
  INA226_REG_BUS_VOLTAGE = 0x02,
  INA226_REG_POWER = 0x03,
  INA226_REG_CURRENT = 0x04,
  INA226_REG_CALIBRATION = 0x05,
  INA226_REG_MASK_OR_ENABLE = 0x06,
  INA226_REG_ALERT_LIMIT = 0x07,
  INA226_REG_MANUFACTURER_ID = 0xFE,
  INA226_REG_DIE_ID = 0xFF,
} INA226_REG;

static inline int ina226_write(const INA226 *ina226, INA226_REG reg, uint16_t data) {
  const uint timeout = 100000;
  const uint8_t buffer[3] = {(uint8_t)reg, (uint8_t)(data >> 8), (uint8_t)(data & 0xff)};
  return i2c_write_timeout_us(ina226->i2c_bus.inst, ina226->i2c_address, buffer, 3, false, timeout);
}

static inline uint16_t ina226_read(const INA226 *ina226, INA226_REG reg) {
  const uint timeout = 100000;
  uint8_t buffer[2] = {(uint8_t)reg, 0};
  int ret =
      i2c_write_timeout_us(ina226->i2c_bus.inst, ina226->i2c_address, buffer, 1, false, timeout);
  if (ret == PICO_ERROR_GENERIC || ret == PICO_ERROR_TIMEOUT) {
    return 0;
  }
  ret = i2c_read_timeout_us(ina226->i2c_bus.inst, ina226->i2c_address, buffer, 2, false, timeout);
  if (ret == PICO_ERROR_GENERIC || ret == PICO_ERROR_TIMEOUT) {
    return 0;
  }
  return ((uint16_t)buffer[0] << 8) | buffer[1];
}

/*
 * Determines the number of samples that are collected and averaged.
 */
typedef enum INA226_CONFIG_AVG {
  INA226_CONFIG_AVG_1 = 0b000,
  INA226_CONFIG_AVG_4 = 0b001,
  INA226_CONFIG_AVG_16 = 0b010,
  INA226_CONFIG_AVG_64 = 0b011,
  INA226_CONFIG_AVG_128 = 0b100,
  INA226_CONFIG_AVG_256 = 0b101,
  INA226_CONFIG_AVG_512 = 0b110,
  INA226_CONFIG_AVG_1024 = 0b111
} INA226_CONFIG_AVG;

/*
 * Sets the conversion time for the bus voltage or shunt voltage measurement.
 */
typedef enum INA226_CONFIG_CT {
  INA226_CONFIG_CT_140us = 0b000,
  INA226_CONFIG_CT_204us = 0b001,
  INA226_CONFIG_CT_332us = 0b010,
  INA226_CONFIG_CT_588us = 0b011,
  INA226_CONFIG_CT_1100us = 0b100,
  INA226_CONFIG_CT_2116us = 0b101,
  INA226_CONFIG_CT_4156us = 0b110,
  INA226_CONFIG_CT_8244us = 0b111
} INA226_CONFIG_CT;

/*
 * Selects continuous, triggered, or power-down mode of operation.
 */
typedef enum INA226_CONFIG_MODE {
  INA226_CONFIG_MODE_SHUTDOWN = 0b000,
  INA226_CONFIG_MODE_SHUNT_TRIGGERED = 0b001,
  INA226_CONFIG_MODE_BUS_TRIGGERED = 0b010,
  INA226_CONFIG_MODE_BUS_SHUNT_TRIGGERED = 0b011,
  // Exact same as INA226_CONFIG_MODE_SHUTDOWN
  INA226_CONFIG_MODE_SHUTDOWN2 = 0b100,
  INA226_CONFIG_MODE_SHUNT_CONTINUOUS = 0b101,
  INA226_CONFIG_MODE_BUS_CONTINUOUS = 0b110,
  INA226_CONFIG_MODE_BUS_SHUNT_CONTINUOUS = 0b111
} INA226_CONFIG_MODE;

typedef enum INA226_ALERT {
  INA226_ALERT_SHUNT_OVERVOLTAGE = 1 << 15,
  INA226_ALERT_SHUNT_UNDERVOLTAGE = 1 << 14,
  INA226_ALERT_BUS_OVERVOLTAGE = 1 << 13,
  INA226_ALERT_BUS_UNDERVOLTAGE = 1 << 12,
  INA226_ALERT_POWER_OVERLIMIT = 1 << 11,
  INA226_ALERT_READY = 1 << 10,
  INA226_ALERT_ACTIVE_HIGH = 1 << 1,
  INA226_ALERT_LATCH = 1,
} INA226_ALERT;

static inline void ina226_configure(const INA226 *ina226, INA226_CONFIG_AVG avg,
                                    INA226_CONFIG_CT bus_voltage, INA226_CONFIG_CT shunt_voltage,
                                    INA226_CONFIG_MODE mode) {
  const uint16_t data =
      (0b100 << 12) | (avg << 9) | (bus_voltage << 6) | (shunt_voltage << 3) | mode;
  ina226_write(ina226, INA226_REG_CONFIGURATION, data);
}

static inline void ina226_configure_alert(INA226 *ina226, uint16_t alert, int32_t shunt_limit_nv,
                                          uint32_t bus_limit_uv, uint32_t power_limit_uw) {
  uint16_t data = 0;
  ina226_write(ina226, INA226_REG_MASK_OR_ENABLE, alert);
  if (alert & INA226_ALERT_SHUNT_OVERVOLTAGE || alert & INA226_ALERT_SHUNT_UNDERVOLTAGE) {
    int16_t limit_int = (int16_t)(shunt_limit_nv / INA226_SHUNT_VOLTAGE_LSB_NV);
    data = *(uint16_t *)&limit_int;
  } else if (alert & INA226_ALERT_BUS_OVERVOLTAGE || alert & INA226_ALERT_BUS_UNDERVOLTAGE) {
    data = bus_limit_uv / INA226_BUS_VOLTAGE_LSB_UV;
  } else if (alert & INA226_ALERT_POWER_OVERLIMIT) {
    data = power_limit_uw / ina226->power_lsb_uw;
  }
  if (data) {
    ina226_write(ina226, INA226_REG_ALERT_LIMIT, data);
  }
  ina226->irq_event_mask =
      alert & INA226_ALERT_ACTIVE_HIGH ? GPIO_IRQ_EDGE_RISE : GPIO_IRQ_EDGE_FALL;
}

static inline void ina226_enable_alert(const INA226 *ina226) {
  ina226_read(ina226, INA226_REG_MASK_OR_ENABLE); // Clear existing interrupts
  gpio_set_irq_enabled(ina226->alert_pin, ina226->irq_event_mask, true);
}

typedef enum INA226_ALERT_FLAG {
  INA226_ALERT_FLAG_ALERT = 1 << 4,
  INA226_ALERT_FLAG_CONVERSION_READY = 1 << 3,
  INA226_ALERT_FLAG_MATH_OVERFLOW = 1 << 2,
} INA226_ALERT_FLAG;

static inline uint ceil_uint_div(uint num, uint denom) { return (num + (denom - 1)) / denom; }

static inline void ina226_calibrate(INA226 *ina226, uint max_current_uA, uint resistance_uohm) {
  ina226->current_lsb_ua = ceil_uint_div(max_current_uA, 32768);
  ina226->power_lsb_uw = ina226->current_lsb_ua * 25;
  const uint16_t cal = 5120000000 / (ina226->current_lsb_ua * resistance_uohm);
  ina226_write(ina226, INA226_REG_CALIBRATION, cal);
}

static inline int32_t ina226_shunt_voltage_nv(const INA226 *ina226) {
  uint16_t shunt_voltage_raw =
      ina226_read(ina226, INA226_REG_SHUNT_VOLTAGE); // 2's complement representation
  // Essentially all compilers uses 2's complement, reinterpret
  // shunt_voltage_raw as signed.
  const int16_t shunt_voltage_signed = *(int16_t *)&shunt_voltage_raw;
  return (int32_t)shunt_voltage_signed * (int)INA226_SHUNT_VOLTAGE_LSB_NV;
}

static inline uint32_t ina226_bus_voltage_uv(const INA226 *ina226) {
  return ina226_read(ina226, INA226_REG_BUS_VOLTAGE) * INA226_BUS_VOLTAGE_LSB_UV;
}

static inline uint32_t ina226_power_uw(const INA226 *ina226) {
  return ina226_read(ina226, INA226_REG_POWER) * ina226->power_lsb_uw;
}

static inline uint32_t ina226_current_ua(const INA226 *ina226) {
  return ina226_read(ina226, INA226_REG_CURRENT) * ina226->current_lsb_ua;
}

typedef struct INA226State {
  absolute_time_t last_read;
  uint64_t power_uws_since_reset;
  int32_t shunt_voltage_nv;
  uint32_t bus_voltage_uv;
  uint32_t power_uw;
  uint32_t current_ua;
} INA226State;

static void ina226_update_state(const INA226 *ina226, INA226State *ina226State) {
  const uint16_t alert = ina226_read(ina226, INA226_REG_MASK_OR_ENABLE);
  if (alert & INA226_ALERT_FLAG_ALERT) {
    log_warn("INA226 alert triggered %x", alert);
  } else if (alert & INA226_ALERT_FLAG_CONVERSION_READY &&
             !(alert & INA226_ALERT_FLAG_MATH_OVERFLOW)) {
    ina226State->shunt_voltage_nv = ina226_shunt_voltage_nv(ina226);
    ina226State->bus_voltage_uv = ina226_bus_voltage_uv(ina226);
    ina226State->power_uw = ina226_power_uw(ina226);
    ina226State->current_ua = ina226_current_ua(ina226);

    const absolute_time_t now = get_absolute_time();
    const int64_t time_passed_us = absolute_time_diff_us(ina226State->last_read, now);
    ina226State->last_read = now;
    ina226State->power_uws_since_reset +=
        (uint64_t)(ina226State->power_uw) / 1000 * time_passed_us / 1000;
  }
}

inline static void emit_ina226_state(const INA226State *ina226State) {
  const uint buf_len =
      sizeof(int32_t) + sizeof(uint32_t) + sizeof(uint32_t) + sizeof(uint64_t) + sizeof(uint32_t);
  uint8_t buffer[buf_len];
  char *cursor = append_int32((char *)buffer, ina226State->shunt_voltage_nv);
  cursor = append_uint32(cursor, ina226State->bus_voltage_uv);
  cursor = append_uint32(cursor, ina226State->power_uw);
  cursor = append_uint64(cursor, ina226State->power_uws_since_reset);
  append_uint32(cursor, ina226State->current_ua);
  emit(EVENT_INA226_STATE, buffer, buf_len);
}
