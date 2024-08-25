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

  uint16_t gyro_sensitivity; // LSB/(deg/s)
  uint16_t accel_sensitivity; // LSB/g
  uint8_t sample_rate; // Hz
} MPU6500;

static inline MPU6500 mpu6500(SPIBus spi_bus, uint8_t fsync_pin, uint8_t int_pin) {
  spi_set_format(spi_bus.inst, 8, SPI_CPOL_0, SPI_CPHA_0, SPI_MSB_FIRST);

  // Ground fsync and int pins, not used
  gpio_init(fsync_pin);
  gpio_set_dir(fsync_pin, GPIO_OUT);
  gpio_put(fsync_pin, false);

  gpio_init(int_pin);
  gpio_set_dir(int_pin, GPIO_OUT);
  gpio_put(int_pin, false);

  return (MPU6500){spi_bus, fsync_pin, int_pin};
}

static inline void mpu6500_write(MPU6500 mpu6500, uint8_t addr, uint8_t data) {
  spi_bus_select(mpu6500.spi_bus);
  spi_write_blocking(mpu6500.spi_bus.inst, (uint8_t[]){addr, data}, 2);
  spi_bus_deselect(mpu6500.spi_bus);
}

typedef enum MPU6500_REG {
  MPU6500_REG_CONFIG = 26,
  MPU6500_REG_GYRO_CONFIG = 27,
  MPU6500_REG_ACCEL_CONFIG = 28,
  MPU6500_REG_ACCEL_CONFIG2 = 29,
  MPU6500_REG_FIFO_ENABLE = 35,
  MPU6500_REG_TEMP_OUT_H = 65,
  MPU6500_REG_TEMP_OUT_L = 66,
  MPU6500_REG_FIFO_COUNT_H = 114,
  MPU6500_REG_FIFO_COUNT_L = 115,
  MPU65000_REG_FIFO_R_W = 116,
  MPU6500_REG_USER_CTRL = 106,
  MPU6500_REG_POWER = 107,
} MPU6500_REG;

static void mpu6500_read(MPU6500 mpu6500, MPU6500_REG reg, uint8_t buf[], uint16_t len) {
  // For this particular device, we send the device the register we want to read
  // first, then subsequently read from the device. The register is auto
  // incrementing, so we don't need to keep sending the register we want, just
  // the first.
  spi_bus_select(mpu6500.spi_bus);
  spi_write_blocking(mpu6500.spi_bus.inst, (uint8_t[]){(uint8_t)(reg | 128)}, 1);
  spi_read_blocking(mpu6500.spi_bus.inst, 0, buf, len);
  spi_bus_deselect(mpu6500.spi_bus);
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

typedef struct MPU6500Data {
  float temp{}; // celsius
  float ang_vel[3]{}; // deg/s
  double direction[3]{}; // deg
  float accel[3]{}; // m/s^2
  double vel[3]{}; // m/s
  double dis[3]{}; // m
  int16_t ang_vel_comp[3]{};
  int16_t accel_comp[3]{};
} MPU6500Data;

static inline void mpu6500_configure(MPU6500 m, MPU6500_CONFIG_GYRO_DPLF gyroDplf,
                                     MPU6500_CONFIG_GYRO gyro, MPU6500_CONFIG_ACCEL_DPLF accelDplf,
                                     MPU6500_CONFIG_ACCEL accel) {
  mpu6500_write(m, MPU6500_REG_POWER, 128); // reset device
  mpu6500_write(m, MPU6500_REG_USER_CTRL,
                MPU6500_FLAGS_USER_CTRL_FIFO_EN | MPU6500_FLAGS_USER_CTRL_I2C_IF_DIS |
                    MPU6500_FLAGS_USER_CTRL_FIFO_RST | MPU6500_FLAGS_USER_CTRL_SIG_COND_RST);
  if (gyroDplf == MPU6500_CONFIG_GYRO_DPLF_BYPASS_8800HZ ||
      gyroDplf == MPU6500_CONFIG_GYRO_DPLF_BYPASS_3600HZ) {
    mpu6500_write(m, MPU6500_REG_CONFIG, (uint8_t)(-gyroDplf));
    mpu6500_write(m, MPU6500_REG_GYRO_CONFIG, gyro << 3);
    m.sample_rate = 32000;
  } else {
    mpu6500_write(m, MPU6500_REG_CONFIG, 0);
    mpu6500_write(m, MPU6500_REG_GYRO_CONFIG, gyro << 3 | gyroDplf);
    if (gyroDplf == MPU6500_CONFIG_GYRO_DPLF_250HZ || gyroDplf == MPU6500_CONFIG_GYRO_DPLF_3600HZ) {
      m.sample_rate = 8000;
    } else {
      m.sample_rate = 1000;
    }
  }
  switch (gyro) {
  case MPU6500_CONFIG_GYRO_250DPS:
    m.gyro_sensitivity = 131;
    break;
  case MPU6500_CONFIG_GYRO_500DPS:
    m.gyro_sensitivity = 65.5;
    break;
  case MPU6500_CONFIG_GYRO_1000DPS:
    m.gyro_sensitivity = 32.8;
    break;
  case MPU6500_CONFIG_GYRO_2000DPS:
    m.gyro_sensitivity = 16.4;
    break;
  }
  mpu6500_write(m, MPU6500_REG_ACCEL_CONFIG, accel << 3);
  switch (accel) {
  case MPU6500_CONFIG_ACCEL_2g:
    m.accel_sensitivity = 16384;
    break;
  case MPU6500_CONFIG_ACCEL_4g:
    m.accel_sensitivity = 8192;
    break;
  case MPU6500_CONFIG_ACCEL_8g:
    m.accel_sensitivity = 4096;
    break;
  case MPU6500_CONFIG_ACCEL_16g:
    m.accel_sensitivity = 2048;
    break;
  }
  mpu6500_write(m, MPU6500_REG_ACCEL_CONFIG2, accelDplf);
  mpu6500_write(m, MPU6500_REG_FIFO_ENABLE,
                MPU6500_CONFIG_FIFO_GYRO_XOUT | MPU6500_CONFIG_FIFO_GYRO_YOUT |
                    MPU6500_CONFIG_FIFO_GYRO_ZOUT | MPU6500_CONFIG_FIFO_ACCEL);
}

inline int16_t bytesToInt(const uint8_t msb, const uint8_t lsb) {
  uint16_t raw = (uint16_t)(msb << 8) | lsb;
  const int16_t reinterpret = *(int16_t *)&raw;
  return reinterpret;
}

#define MPU6500_FIFO_BYTES_PER_WRITE 12U

static int mpu6500_get_fifo_data_count(MPU6500 m) {
  uint8_t int16_buffer[2];
  mpu6500_read(m, MPU6500_REG_FIFO_COUNT_H, int16_buffer, 2);
  const uint fifo_count = (int16_buffer[0] & 0b00011111) << 8 | int16_buffer[1];
  if (fifo_count == 0) {
    return -1;
  }
  return (int)fifo_count;
}

static void mpu6500_fifo_data(MPU6500 m, MPU6500Data *mpu6500Data) {
  const int fifo_count = mpu6500_get_fifo_data_count(m);
  if (fifo_count == -1)
    return;
  const uint dataset_count = fifo_count / MPU6500_FIFO_BYTES_PER_WRITE;

  uint8_t fifo_buffer[512];
  mpu6500_read(m, MPU65000_REG_FIFO_R_W, fifo_buffer, fifo_count);
  if (fifo_count != dataset_count * MPU6500_FIFO_BYTES_PER_WRITE) {
    log_warn("fifo count indivisible by %d: %d", MPU6500_FIFO_BYTES_PER_WRITE, fifo_count);
  }
  for (uint i = 0; i < dataset_count; ++i) {
    const uint offset = i * MPU6500_FIFO_BYTES_PER_WRITE;
    for (uint j = 0; j < 3; ++j) {
      mpu6500Data->accel[j] =
          (float)(bytesToInt(fifo_buffer[offset + j], fifo_buffer[offset + j + 1]) +
                  mpu6500Data->accel_comp[j]) *
          9.8067f / m.accel_sensitivity;
      mpu6500Data->vel[j] += mpu6500Data->accel[j] / m.sample_rate;
      mpu6500Data->dis[j] += mpu6500Data->vel[j] / m.sample_rate;
    }
    for (uint j = 0; j < 3; ++j) {
      mpu6500Data->ang_vel[j] =
          (float)(mpu6500Data->ang_vel_comp[j] +
                  bytesToInt(fifo_buffer[offset + 6 + j], fifo_buffer[offset + 7 + j]) +
                  mpu6500Data->ang_vel_comp[j]) /
          m.gyro_sensitivity;
      mpu6500Data->direction[i] += mpu6500Data->ang_vel[i] / m.sample_rate;
    }
  }

  uint8_t temp_reg_buffer[2];
  mpu6500_read(m, MPU6500_REG_TEMP_OUT_H, temp_reg_buffer, 2);
  mpu6500Data->temp = (float)bytesToInt(temp_reg_buffer[0], temp_reg_buffer[1]) / 333.87f +
                      21; // RoomTemp_Offset is 0,  Temp_Sensitivity=333.87
}

static inline void mpu6500_calibrate_when_stationary(MPU6500 m, MPU6500Data *mpu6500Data) {
  const uint readings_count = 1024;
  int16_t accel_readings[3][readings_count];
  int16_t gyro_readings[3][readings_count];
  for (int i = 0; i < readings_count; i++) {
    const int fifo_count = mpu6500_get_fifo_data_count(m);
    if (fifo_count == -1)
      return;
    const uint dataset_count = fifo_count / MPU6500_FIFO_BYTES_PER_WRITE;

    uint8_t fifo_buffer[512];
    mpu6500_read(m, MPU65000_REG_FIFO_R_W, fifo_buffer, fifo_count);
    if (fifo_count != dataset_count * MPU6500_FIFO_BYTES_PER_WRITE) {
      log_warn("fifo count indivisible by %d: %d", MPU6500_FIFO_BYTES_PER_WRITE, fifo_count);
    }
    for (uint j = 0; j < dataset_count; ++j) {
      const uint offset = i * MPU6500_FIFO_BYTES_PER_WRITE;
      for (uint k = 0; k < 3; ++k) {
        accel_readings[k][i] = bytesToInt(fifo_buffer[offset + j], fifo_buffer[offset + j + 1]);
      }
      for (uint k = 0; k < 3; ++k) {
        gyro_readings[k][i] = bytesToInt(fifo_buffer[offset + j + 6], fifo_buffer[offset + j + 7]);
      }
    }
  }
  for (int i = 0; i < 3; i++) {
    int32_t sum = 0;
    for (int j = 0; j < readings_count; j++) {
      sum += accel_readings[i][j];
    }
    mpu6500Data->accel_comp[i] = (int16_t)(sum / readings_count);
  }
  for (int i = 0; i < 3; i++) {
    int32_t sum = 0;
    for (int j = 0; j < readings_count; j++) {
      sum += gyro_readings[i][j];
    }
    mpu6500Data->ang_vel_comp[i] = (int16_t)(sum / readings_count);
  }
}