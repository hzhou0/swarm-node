#pragma once
#include "hardware/spi.h"
#include "io.h"
#include "math.h"
#include "pico/stdlib.h"

#define SPI_1MHZ (1000 * 1000)

typedef struct SPIBus {
  struct spi_inst *inst;
  uint8_t sck_pin;
  uint8_t tx_pin;
  uint8_t rx_pin;
  uint8_t csn_pin;
} SPIBus;

static inline void spi_bus_select(SPIBus spi_bus) {
  asm volatile("nop \n nop \n nop");
  gpio_put(spi_bus.csn_pin, false); // Active low
  asm volatile("nop \n nop \n nop");
}

static inline void spi_bus_deselect(SPIBus spi_bus) {
  asm volatile("nop \n nop \n nop");
  gpio_put(spi_bus.csn_pin, true);
  asm volatile("nop \n nop \n nop");
}

static inline SPIBus spi_bus(struct spi_inst *inst, uint8_t sck_pin, uint8_t tx_pin, uint8_t rx_pin,
                             uint8_t csn_pin) {
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
  uint32_t irq_event_mask;

  float gyro_sensitivity; // LSB/(deg/s)
  uint16_t accel_sensitivity; // LSB/g
  uint16_t sample_rate; // Hz
} MPU6500;

static inline MPU6500 mpu6500(SPIBus spi_bus, uint8_t fsync_pin, uint8_t int_pin) {
  spi_set_format(spi_bus.inst, 8, SPI_CPOL_0, SPI_CPHA_0, SPI_MSB_FIRST);

  gpio_init(fsync_pin);
  gpio_set_dir(fsync_pin, GPIO_IN);

  gpio_init(int_pin);
  gpio_set_dir(int_pin, GPIO_IN);

  return (MPU6500){spi_bus, fsync_pin, int_pin};
}

static inline void mpu6500_write(const MPU6500 *mpu6500, uint8_t addr, uint8_t data) {
  spi_bus_select(mpu6500->spi_bus);
  spi_write_blocking(mpu6500->spi_bus.inst, (uint8_t[]){addr, data}, 2);
  spi_bus_deselect(mpu6500->spi_bus);
  sleep_us(1);
}

typedef enum MPU6500_REG {
  MPU6500_REG_RATE_DIVIDER = 25,
  MPU6500_REG_CONFIG = 26,
  MPU6500_REG_GYRO_CONFIG = 27,
  MPU6500_REG_ACCEL_CONFIG = 28,
  MPU6500_REG_ACCEL_CONFIG2 = 29,
  MPU6500_REG_FIFO_ENABLE = 35,
  MPU6500_REG_INT_PIN_CFG = 55,
  MPU6500_REG_INT_ENABLE = 56,
  MPU6500_REG_INT_STATUS = 58,
  MPU6500_REG_ACCEL_XOUT_H = 59,
  MPU6500_REG_ACCEL_XOUT_L = 60,
  MPU6500_REG_ACCEL_YOUT_H = 61,
  MPU6500_REG_ACCEL_YOUT_L = 62,
  MPU6500_REG_ACCEL_ZOUT_H = 63,
  MPU6500_REG_ACCEL_ZOUT_L = 64,
  MPU6500_REG_TEMP_OUT_H = 65,
  MPU6500_REG_TEMP_OUT_L = 66,
  MPU6500_REG_GYRO_XOUT_H = 67,
  MPU6500_REG_GYRO_XOUT_L = 68,
  MPU6500_REG_GYRO_YOUT_H = 69,
  MPU6500_REG_GYRO_YOUT_L = 70,
  MPU6500_REG_GYRO_ZOUT_H = 71,
  MPU6500_REG_GYRO_ZOUT_L = 72,
  MPU6500_REG_FIFO_COUNT_H = 114,
  MPU6500_REG_FIFO_COUNT_L = 115,
  MPU6500_REG_FIFO_R_W = 116,
  MPU6500_REG_USER_CTRL = 106,
  MPU6500_REG_POWER = 107,
  MPU6500_REG_WHOAMI = 117
} MPU6500_REG;

static void mpu6500_read(const MPU6500 *mpu6500, MPU6500_REG reg, uint8_t buf[], uint16_t len) {
  // For this particular device, we send the device the register we want to read
  // first, then subsequently read from the device. The register is auto
  // incrementing, so we don't need to keep sending the register we want, just
  // the first.
  const uint8_t addr = reg | 128;
  spi_bus_select(mpu6500->spi_bus);
  spi_write_blocking(mpu6500->spi_bus.inst, &addr, 1);
  spi_read_blocking(mpu6500->spi_bus.inst, 0, buf, len);
  spi_bus_deselect(mpu6500->spi_bus);
}

static uint8_t mpu6500_read1(const MPU6500 *mpu6500, MPU6500_REG reg) {
  // For this particular device, we send the device the register we want to read
  // first, then subsequently read from the device. The register is auto
  // incrementing, so we don't need to keep sending the register we want, just
  // the first.
  const uint8_t addr = reg | 128;
  uint8_t buf[1];
  spi_bus_select(mpu6500->spi_bus);
  spi_write_blocking(mpu6500->spi_bus.inst, &addr, 1);
  spi_read_blocking(mpu6500->spi_bus.inst, 0, buf, 1);
  spi_bus_deselect(mpu6500->spi_bus);
  return buf[0];
}

typedef enum MPU6500_CONFIG_GYRO_DPLF {
  MPU6500_CONFIG_GYRO_DPLF_250HZ = 0,
  MPU6500_CONFIG_GYRO_DPLF_184HZ = 1,
  MPU6500_CONFIG_GYRO_DPLF_92HZ = 2,
  MPU6500_CONFIG_GYRO_DPLF_41HZ = 3,
  MPU6500_CONFIG_GYRO_DPLF_20HZ = 4,
  MPU6500_CONFIG_GYRO_DPLF_10HZ = 5,
  MPU6500_CONFIG_GYRO_DPLF_5HZ = 6,
  MPU6500_CONFIG_GYRO_DPLF_3600HZ = 7,
  MPU6500_CONFIG_GYRO_DPLF_BYPASS_8800HZ = -0b11,
  MPU6500_CONFIG_GYRO_DPLF_BYPASS_3600HZ = -0b10
} MPU6500_CONFIG_GYRO_DPLF;

typedef enum MPU6500_CONFIG_GYRO {
  MPU6500_CONFIG_GYRO_250DPS = 0b00, // degrees per second
  MPU6500_CONFIG_GYRO_500DPS = 0b01,
  MPU6500_CONFIG_GYRO_1000DPS = 0b10,
  MPU6500_CONFIG_GYRO_2000DPS = 0b11,
} MPU6500_CONFIG_GYRO;

typedef enum MPU6500_CONFIG_ACCEL_DPLF {
  MPU6500_CONFIG_ACCEL_DPLF_BYPASS_1130HZ = 0b1000,
  MPU6500_CONFIG_ACCEL_DPLF_460HZ = 0,
  MPU6500_CONFIG_ACCEL_DPLF_184HZ = 1,
  MPU6500_CONFIG_ACCEL_DPLF_92HZ = 2,
  MPU6500_CONFIG_ACCEL_DPLF_41HZ = 3,
  MPU6500_CONFIG_ACCEL_DPLF_20HZ = 4,
  MPU6500_CONFIG_ACCEL_DPLF_10HZ = 5,
  MPU6500_CONFIG_ACCEL_DPLF_5HZ = 6,
  MPU6500_CONFIG_ACCEL_DPLF_460HZ2 = 7,
} MPU6500_CONFIG_ACCEL_DPLF;

typedef enum MPU6500_CONFIG_ACCEL {
  MPU6500_CONFIG_ACCEL_2g = 0b00, // gravitational constant
  MPU6500_CONFIG_ACCEL_4g = 0b01,
  MPU6500_CONFIG_ACCEL_8g = 0b10,
  MPU6500_CONFIG_ACCEL_16g = 0b11,
} MPU6500_CONFIG_ACCEL;

typedef enum MPU6500_CONFIG_FIFO {
  MPU6500_CONFIG_FIFO_TEMP_OUT = 128,
  MPU6500_CONFIG_FIFO_GYRO_XOUT = 64,
  MPU6500_CONFIG_FIFO_GYRO_YOUT = 32,
  MPU6500_CONFIG_FIFO_GYRO_ZOUT = 16,
  MPU6500_CONFIG_FIFO_ACCEL = 8,
  MPU6500_CONFIG_FIFO_SLV_2 = 4,
  MPU6500_CONFIG_FIFO_SLV_1 = 2,
  MPU6500_CONFIG_FIFO_SLV_0 = 1,
  MPU6500_CONFIG_FIFO_NULL = 0
} MPU6500_CONFIG_FIFO;

typedef enum MPU6500_FLAGS_USER_CTRL {
  MPU6500_FLAGS_USER_CTRL_DMP_EN = 128,
  MPU6500_FLAGS_USER_CTRL_FIFO_EN = 64,
  MPU6500_FLAGS_USER_CTRL_I2C_MST_EN = 32,
  MPU6500_FLAGS_USER_CTRL_I2C_IF_DIS = 16,
  MPU6500_FLAGS_USER_CTRL_DMP_RST = 8,
  MPU6500_FLAGS_USER_CTRL_FIFO_RST = 4,
  MPU6500_FLAGS_USER_CTRL_I2C_MST_RST = 2,
  MPU6500_FLAGS_USER_CTRL_SIG_COND_RST = 1,
  MPU6500_FLAGS_USER_CTRL_NULL = 0
} MPU6500_FLAGS_USER_CTRL;

static inline void mpu6500_configure(MPU6500 *m, MPU6500_CONFIG_GYRO_DPLF gyroDplf,
                                        MPU6500_CONFIG_GYRO gyro,
                                        MPU6500_CONFIG_ACCEL_DPLF accelDplf,
                                        MPU6500_CONFIG_ACCEL accel) {
  uint8_t buf[1] = {};
  mpu6500_read(m, MPU6500_REG_WHOAMI, buf, 1);
  if (buf[0] != 0x70) {
    log_critical("Unexpected whoami register value for mpu6500, %d (should be 0x70)", buf[0]);
  }

  mpu6500_write(m, MPU6500_REG_POWER, 128); // reset device
  sleep_ms(1);
  mpu6500_write(m, MPU6500_REG_USER_CTRL,
                MPU6500_FLAGS_USER_CTRL_I2C_IF_DIS | MPU6500_FLAGS_USER_CTRL_SIG_COND_RST);
  if (gyroDplf == MPU6500_CONFIG_GYRO_DPLF_BYPASS_8800HZ ||
      gyroDplf == MPU6500_CONFIG_GYRO_DPLF_BYPASS_3600HZ) {
    mpu6500_write(m, MPU6500_REG_GYRO_CONFIG, gyro << 3 | (uint8_t)(-gyroDplf));
    m->sample_rate = 32000u;
  } else {
    mpu6500_write(m, MPU6500_REG_CONFIG, gyroDplf);
    mpu6500_write(m, MPU6500_REG_GYRO_CONFIG, gyro << 3);
    if (gyroDplf == MPU6500_CONFIG_GYRO_DPLF_250HZ || gyroDplf == MPU6500_CONFIG_GYRO_DPLF_3600HZ) {
      m->sample_rate = 8000u;
    } else {
      m->sample_rate = 1000u;
    }
  }
  switch (gyro) {
  case MPU6500_CONFIG_GYRO_250DPS:
    m->gyro_sensitivity = 131;
    break;
  case MPU6500_CONFIG_GYRO_500DPS:
    m->gyro_sensitivity = 65.5f;
    break;
  case MPU6500_CONFIG_GYRO_1000DPS:
    m->gyro_sensitivity = 32.8f;
    break;
  case MPU6500_CONFIG_GYRO_2000DPS:
    m->gyro_sensitivity = 16.4f;
    break;
  }
  mpu6500_write(m, MPU6500_REG_ACCEL_CONFIG, accel << 3);
  switch (accel) {
  case MPU6500_CONFIG_ACCEL_2g:
    m->accel_sensitivity = 16384;
    break;
  case MPU6500_CONFIG_ACCEL_4g:
    m->accel_sensitivity = 8192;
    break;
  case MPU6500_CONFIG_ACCEL_8g:
    m->accel_sensitivity = 4096;
    break;
  case MPU6500_CONFIG_ACCEL_16g:
    m->accel_sensitivity = 2048;
    break;
  }
  mpu6500_write(m, MPU6500_REG_ACCEL_CONFIG2, accelDplf);
}

typedef struct MPU6500State {
  float temp; // celsius
  float ang_vel[3]; // deg/s
  double direction[3]; // deg
  float accel[3]; // m/s^2
  double vel[3]; // m/s
  double displacement[3]; // m
  int16_t ang_vel_comp[3];
  int16_t accel_comp[3];
} MPU6500State;

static bool mpu6500_raw_data_ready(const MPU6500 *m) {
  return mpu6500_read1(m, MPU6500_REG_INT_STATUS) & 1;
}

static void mpu6500_update_state(const MPU6500 *m, MPU6500State *mpu6500State) {
  uint8_t buf[14];
  static absolute_time_t last_update = 0;
  const absolute_time_t current_time = get_absolute_time();
  const int64_t time_elapsed_us = absolute_time_diff_us(last_update, current_time);
  const double time_elapsed_secs = time_elapsed_us / 1000000.0;
  last_update = current_time;
  mpu6500_read(m, MPU6500_REG_ACCEL_XOUT_H, buf, 14);
  for (uint i = 0; i < 3; ++i) {
    mpu6500State->accel[i] =
        (float)(bytesToInt(buf[i * 2], buf[i * 2 + 1]) + mpu6500State->accel_comp[i]) * 9.8067f /
        (float)m->accel_sensitivity;
    if (fabsf(mpu6500State->accel[i]) > 0.1) {
      mpu6500State->vel[i] += (double)mpu6500State->accel[i] * time_elapsed_secs;
      mpu6500State->displacement[i] += mpu6500State->vel[i] * time_elapsed_secs;
    }

    mpu6500State->ang_vel[i] =
        (float)(bytesToInt(buf[i * 2 + 8], buf[i * 2 + 9]) + mpu6500State->ang_vel_comp[i]) /
        m->gyro_sensitivity;
    if (fabsf(mpu6500State->ang_vel[i]) > 0.1) {
      mpu6500State->direction[i] += mpu6500State->ang_vel[i] * time_elapsed_secs;
    }
  }
  mpu6500State->temp = (float)bytesToInt(buf[6], buf[7]) / 333.87f + 21;
}

static void mpu6500_data_restart_odom(MPU6500State *mpu6500Data) {
  for (int i = 0; i < 3; ++i) {
    mpu6500Data->vel[i] = 0;
    mpu6500Data->displacement[i] = 0;
    mpu6500Data->direction[i] = 0;
  }
}

static void mpu6500_calibrate_while_stationary(const MPU6500 *m, MPU6500State *mpu6500Data) {
  const int32_t readings_count = 2048;
  int32_t accel_accum[3] = {0, 0, 0};
  int32_t gyro_accum[3] = {0, 0, 0};
  for (uint i = 0; i < readings_count; ++i) {
    uint8_t buf[14];
    while (!mpu6500_raw_data_ready(m)) {
      sleep_us(1);
    }
    sleep_us(1); // required for reading to be accurate
    mpu6500_read(m, MPU6500_REG_ACCEL_XOUT_H, buf, 14);
    for (uint j = 0; j < 3; ++j) {
      accel_accum[j] += (int32_t)bytesToInt(buf[j * 2], buf[j * 2 + 1]);
      gyro_accum[j] += (int32_t)bytesToInt(buf[j * 2 + 8], buf[j * 2 + 9]);
    }
  }
  for (int i = 0; i < 3; i++) {
    mpu6500Data->accel_comp[i] = (int16_t)(-accel_accum[i] / readings_count);
  }
  for (int i = 0; i < 3; i++) {
    mpu6500Data->ang_vel_comp[i] = (int16_t)(-gyro_accum[i] / readings_count);
  }
}

typedef enum MPU6500_FLAGS_INT_EN {
  MPU6500_FLAGS_INT_WOM_EN = 64,
  MPU6500_FLAGS_INT_FIFO_OVERFLOW_EN = 16,
  MPU6500_FLAGS_INT_FSYNC_INT_EN = 8,
  MPU6500_FLAGS_INT_RAW_RDY_EN = 1,
  MPU6500_FLAGS_INT_NULL = 0
} MPU6500_FLAGS_INT_EN;

typedef enum MPU6500_FLAGS_INT_CONFIG {
  MPU6500_FLAGS_INT_CONFIG_ACTIVE_LOW = 128,
  MPU6500_FLAGS_INT_CONFIG_OPEN_DRAIN = 64,
  MPU6500_FLAGS_INT_CONFIG_LATCH = 32,
  MPU6500_FLAGS_INT_CONFIG_ANYREAD2CLEAR = 16,
  MPU6500_FLAGS_INT_CONFIG_FSYNC_ACTIVE_LOW = 8,
  MPU6500_FLAGS_INT_CONFIG_FSYNC_EN = 4,
  MPU6500_FLAGS_INT_CONFIG_BYPASS_EN = 2,
  MPU6500_FLAGS_INT_CONFIG_NULL = 0,
} MPU6500_FLAGS_INT_CONFIG;

static inline void mpu6500_configure_alert(MPU6500 *m, uint8_t mpu_6500_flags_int_en,
                                           uint8_t mpu_6500_flags_int_config) {
  mpu6500_write(m, MPU6500_REG_INT_ENABLE, mpu_6500_flags_int_en);
  mpu6500_write(m, MPU6500_REG_INT_PIN_CFG, mpu_6500_flags_int_config);
  m->irq_event_mask = mpu_6500_flags_int_config & MPU6500_FLAGS_INT_CONFIG_ACTIVE_LOW
                         ? GPIO_IRQ_EDGE_FALL
                         : GPIO_IRQ_EDGE_RISE;
}

static inline void mpu6500_enable_alert(const MPU6500 *m) {
  mpu6500_read1(m, MPU6500_REG_INT_STATUS); // Clear existing interrupts
  gpio_set_irq_enabled(m->int_pin, m->irq_event_mask, true);
}

inline static void emit_mpu6500_state(const MPU6500State *mpu6500State) {
  const uint buf_len = sizeof(float) + sizeof(float) * 3 + sizeof(double) * 3 + sizeof(float) * 3 +
                       sizeof(double) * 3 + sizeof(double) * 3;
  uint8_t buffer[buf_len];
  char *cursor = append_float((char *)buffer, mpu6500State->temp);
  for (int i = 0; i < 3; ++i) {
    cursor = append_float(cursor, mpu6500State->ang_vel[i]);
  }
  for (int i = 0; i < 3; ++i) {
    cursor = append_double(cursor, mpu6500State->direction[i]);
  }
  for (int i = 0; i < 3; ++i) {
    cursor = append_float(cursor, mpu6500State->accel[i]);
  }
  for (int i = 0; i < 3; ++i) {
    cursor = append_double(cursor, mpu6500State->vel[i]);
  }
  for (int i = 0; i < 3; ++i) {
    cursor = append_double(cursor, mpu6500State->displacement[i]);
  }
  emit(EVENT_MPU6500_STATE, buffer, buf_len);
}