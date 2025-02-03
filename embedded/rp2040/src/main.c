/**
Using GTK+ convention:
- All macros and constants in caps: MAX_BUFFER_SIZE, TRACKING_ID_PREFIX.
- Struct names and typedef's in camelcase: GtkWidget, TrackingOrder.
- Functions that operate on structs: classic C style: gtk_widget_show(),
tracking_order_process().
- Pointers: nothing fancy here: GtkWidget *foo, TrackingOrder *bar.
- Global variables: just don't use global variables. They are evil.
 */
#define PICO_STDIO_USB_CONNECT_WAIT_TIMEOUT_MS (-10)

#include "gpi.h"
#include "i2c.h"
#include "io.h"
#include "pico/stdlib.h"
#include "servo.h"
#include "spi.h"

#include <hardware/watchdog.h>

typedef struct State {
  GPIState gpi_state;
  INA226State current_sensor_state;
  MPU6500State imu_state;
} State;

INA226 current_sensor;
State state;
MPU6500 imu;
int16_t emit_state_interval_ms = -1;
bool emit_loop_perf = false;

volatile bool imu_irq_flag = false;
volatile bool current_sensor_irq_flag = false;

void gpio_callback(uint gpio, uint32_t event_masks) {
  gpio_set_irq_enabled(gpio, event_masks, false);
  //  gpi_alert_irq_handler(gpio, &state.gpi_state);
  if (gpio == imu.int_pin) {
    imu_irq_flag = true;
  } else if (gpio == current_sensor.alert_pin) {
    current_sensor_irq_flag = true;
  }
}

void process_commands(State *state, const MPU6500 mpu6500) {
  static bool end_of_frame = true, start_of_frame = false;
  static uint8_t decode_buf[MUT_BUF_LEN];
  static uint decode_len = 0;
  int c;
  // mutation frames begin and end with \0
  while (start_of_frame == false && decode_len == 0) {
  // Read until end of frame
  find_end_of_frame:
    while (end_of_frame == false) {
      c = getchar_timeout_us(0);
      switch (c) {
      case PICO_ERROR_TIMEOUT:
        return;
      case 0:
        end_of_frame = true;
      default:;
      }
    }
    // start of frame should follow end of frame
    // if not SoF, then the previous char wasn't the EoF. Keep looking for EoF.
    c = getchar_timeout_us(0);
    switch (c) {
    case PICO_ERROR_TIMEOUT:
      return;
    case 0:
      end_of_frame = false;
      start_of_frame = true;
      break;
    default:
      end_of_frame = false;
      goto find_end_of_frame;
    }
  }
  while (true) {
    c = getchar_timeout_us(0);
    if (c == PICO_ERROR_TIMEOUT) {
      return;
    }
    start_of_frame = false;
    if (c == 0) {
      end_of_frame = true;
      break;
    }
    if (decode_len >= MUT_BUF_LEN) {
      log_error("msg overflowed buffer");
      decode_len = 0;
      return;
    }
    decode_buf[decode_len] = c;
    decode_len++;
  }
  uint8_t mutation_buf[MUT_BUF_LEN];
  const cobs_decode_result res = cobs_decode(mutation_buf, MUT_BUF_LEN, decode_buf, decode_len);
  decode_len = 0;
  if (res.status != COBS_DECODE_OK) {
    log_error("cobs decode error");
    return;
  }

  ServoDegreesMutation sd_mut = {};
  switch (mutation_buf[0]) {
  case MUTATION_SERVO_DEGREES:
    if (res.out_len - 1 != 12) {
      log_error("mutation %d with invalid length %d", mutation_buf[0], res.out_len);
      return;
    }
    for (int i = 0; i < 3; ++i) {
      sd_mut.right_front[i] = mutation_buf[i + 1];
      sd_mut.right_back[i] = mutation_buf[i + 6 + 1];
      sd_mut.left_front[i] = mutation_buf[i + 3 + 1];
      sd_mut.left_back[i] = mutation_buf[i + 9 + 1];
    }
    break;
  case MUTATION_REQUEST_STATE:
    if (res.out_len - 1 != 0) {
      log_error("mutation %d with invalid length %d", mutation_buf[0], res.out_len);
      return;
    }
    emit_ina226_state(&state->current_sensor_state);
    emit_gpi_state(&state->gpi_state);
    emit_mpu6500_state(&state->imu_state);
    break;
  case MUTATION_MPU6500_CALIBRATE:
    if (res.out_len - 1 != 0) {
      log_error("mutation %d with invalid length %d", mutation_buf[0], res.out_len);
      return;
    }
    mpu6500_calibrate_while_stationary(&mpu6500, &state->imu_state);
    break;
  case MUTATION_EMIT_BUFFERED_ERROR_LOG:
    if (res.out_len - 1 != 0) {
      log_error("mutation %d with invalid length %d", mutation_buf[0], res.out_len);
      return;
    }
    emit_buffered_error();
    break;
  case MUTATION_MPU6500_RESET_ODOM:
    if (res.out_len - 1 != 0) {
      log_error("mutation %d with invalid length %d", mutation_buf[0], res.out_len);
      return;
    }
    mpu6500_data_restart_odom(&state->imu_state);
    break;
  case MUTATION_SET_PROGRAM_OPTIONS:
    if (res.out_len - 1 != 4) {
      log_error("mutation %d with invalid length %d", mutation_buf[0], res.out_len);
      return;
    }
    log_level = mutation_buf[1];
    emit_state_interval_ms = bytesToInt(mutation_buf[2], mutation_buf[3]);
    emit_loop_perf = (bool)mutation_buf[4];
    break;
  default:
    log_error("Unknown mutation type %d", mutation_buf[0]);
    break;
  }
}

int main() {
  // System level initialization
  stdio_init_all();
  gpio_set_irq_callback(gpio_callback);
  irq_set_enabled(IO_IRQ_BANK0, true);

  // I2C Devices
  const I2CBus bus0 = i2c_bus(i2c0, 1, 0, I2C_SPEED_FAST);
  I2CBus bus1 = i2c_bus(i2c1, 3, 2, I2C_SPEED_STD);
  current_sensor = ina226(bus0, 0b1000000, 12, 20 * 1000 * 1000, 2 * 1000);
  ina226_configure(&current_sensor, INA226_CONFIG_AVG_1, INA226_CONFIG_CT_1100us,
                   INA226_CONFIG_CT_1100us, INA226_CONFIG_MODE_BUS_SHUNT_CONTINUOUS);
  ina226_configure_alert(&current_sensor, INA226_ALERT_READY, 0, 0, 0);
  ina226_enable_alert(&current_sensor);
  /*
  // GPIO devices
  LegServos leg_servos = leg_servo_init();
  gpi_init();
  // gpi_enable_alert();
  */
  // SPI Devices
  const SPIBus spi_bus1 = spi_bus(spi1, 26, 27, 28, 29);
  imu = mpu6500(spi_bus1, 22, 21);
  mpu6500_configure(&imu, MPU6500_CONFIG_GYRO_DPLF_184HZ, MPU6500_CONFIG_GYRO_250DPS,
                    MPU6500_CONFIG_ACCEL_DPLF_184HZ, MPU6500_CONFIG_ACCEL_2g);
  mpu6500_calibrate_while_stationary(&imu, &state.imu_state);
  mpu6500_configure_alert(&imu, MPU6500_FLAGS_INT_RAW_RDY_EN, MPU6500_FLAGS_INT_CONFIG_NULL);
  mpu6500_data_restart_odom(&state.imu_state);
  mpu6500_enable_alert(&imu);

  absolute_time_t next_update_time = get_absolute_time();
  uint16_t loop_counter = 0;
  MainLoopPerf perf = {0, 0};

  uint32_t servo_loop_counter = 1;
  int8_t current_dir = 1;
  Servo servo1 = servo_init(15);
  Servo servo2 = servo_init(18);

  bool in_sweep = false;
  uint8_t servo1_sweep_angle_deg = 0;
  uint8_t servo2_sweep_angle_deg = 0;
  int8_t servo1_dir = 1;
  int8_t servo2_dir = 1;
  uint8_t servo1_sweep_start_deg = 0;
  uint8_t servo1_sweep_end_deg = SERVO_RANGE_DEG;
  uint8_t servo2_sweep_start_deg = 0;
  uint8_t servo2_sweep_end_deg = SERVO_RANGE_DEG;
  const uint8_t SWEEP_INCREMENT_DEG = 30;
  const uint16_t SWEEP_INCREMENT_INTERVAL_MS = 750;
  absolute_time_t sweep_update_time = get_absolute_time();
  
  while (true) {
    process_commands(&state, imu);

    if (imu_irq_flag) {
      // log_debug("imu irq");
      imu_irq_flag = false;
      mpu6500_read1(&imu, MPU6500_REG_INT_STATUS);
      mpu6500_update_state(&imu, &state.imu_state);
      mpu6500_enable_alert(&imu);
    } else if (current_sensor_irq_flag) {
      current_sensor_irq_flag = false;
      ina226_update_state(&current_sensor, &state.current_sensor_state);
      ina226_enable_alert(&current_sensor);
    } else if (emit_state_interval_ms >= 0 && time_reached(next_update_time)) {
      emit_ina226_state(&state.current_sensor_state);
      emit_mpu6500_state(&state.imu_state);
      next_update_time = delayed_by_ms(get_absolute_time(), emit_state_interval_ms);
    } else if (emit_loop_perf) {
      perf.idle_loops_per_10000++;
    }

    if (in_sweep && time_reached(sweep_update_time)) {
      if (servo1_sweep_angle_deg == servo1_sweep_end_deg) {
        // Servo 1 has reached the end, so reverse it.
        servo1_dir *= -1;
        if (servo2_sweep_angle_deg == servo2_sweep_end_deg) {
          // If both servos have reached the end, the sweep is done.
          in_sweep = false;
          // Reverse the direction of Servo 2 for the next time it is used.
          servo2_dir *= -1;
        }
        else {
          uint8_t tmp_angle = servo1_sweep_start_deg;
          servo1_sweep_start_deg = servo1_sweep_end_deg;
          servo1_sweep_end_deg = tmp_angle;
          // Update and move Servo 2.
          servo2_sweep_angle_deg += SWEEP_INCREMENT_DEG * servo2_dir;
          servo_set(servo2, servo2_sweep_angle_deg);
        }
      }
      else {
        servo1_sweep_angle_deg += SWEEP_INCREMENT_DEG * servo1_dir;
        servo_set(servo1, servo1_sweep_angle_deg);
      }

      sweep_update_time = delayed_by_ms(get_absolute_time(), SWEEP_INCREMENT_INTERVAL_MS);
    }

    if ((++servo_loop_counter % 2000000 == 0) && (!in_sweep)) {
      servo_loop_counter = 1;

      // current_dir *= -1;
      // if (current_dir == -1) {
      //   servo_set(servo1, 0);
      //   servo_set(servo2, 0);
      //   log_error("0 DEG");
      // }
      // else if (current_dir == 1) {
      //   servo_set(servo1, 180);
      //   servo_set(servo1, 180);
      //   log_error("180 DEG");
      // }

      in_sweep = true;
      servo1_sweep_start_deg = (servo1_dir == 1) ? 30: 150;
      servo2_sweep_start_deg = (servo2_dir == 1) ? 30: 150;
      servo1_sweep_end_deg = (servo1_dir == 1) ? 150: 30;
      servo2_sweep_end_deg = (servo2_dir == 1) ? 150: 30;

      servo1_sweep_angle_deg = servo1_sweep_start_deg;
      servo2_sweep_angle_deg = servo2_sweep_start_deg;
      servo_set(servo1, servo1_sweep_angle_deg);
      servo_set(servo2, servo2_sweep_angle_deg);
      sweep_update_time = delayed_by_ms(get_absolute_time(), 3*SWEEP_INCREMENT_INTERVAL_MS);
    }

    if (emit_loop_perf && ++loop_counter >= 10000) {
      perf.us_per_10000 = absolute_time_diff_us(perf.us_per_10000, get_absolute_time());
      emit_idle_loops_count_per_10000(perf);
      loop_counter = 0;
      perf.idle_loops_per_10000 = 0;
      perf.us_per_10000 = get_absolute_time();
    }
  }
}
