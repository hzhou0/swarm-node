#pragma once

#include "hardware/clocks.h"
#include "hardware/pwm.h"
#include "pico/stdlib.h"

typedef struct PWM {
  uint8_t slice;
  uint8_t channel;
} PWM;
typedef PWM Servo;

#define SERVO_PERIOD_HZ 50
#define SERVO_CLK_DIV 250

static inline PWM pwm(uint pin, float freqHz) {
  PWM pwm;
  gpio_set_function(pin, GPIO_FUNC_PWM);
  pwm.slice = pwm_gpio_to_slice_num(pin);
  pwm.channel = pwm_gpio_to_channel(pin);
  const uint32_t core_clk_hz = clock_get_hz(clk_sys);
  pwm_set_clkdiv(pwm.slice, SERVO_CLK_DIV);
  pwm_set_wrap(pwm.slice, (core_clk_hz / SERVO_CLK_DIV) / SERVO_PERIOD_HZ);
  pwm_set_chan_level(pwm.slice, pwm.channel, 0);
  pwm_set_enabled(pwm.slice, true);
  return pwm;
}

inline static void pwm_set(PWM x, uint16_t dutyCycle) { pwm_set_chan_level(x.slice, x.channel, dutyCycle); }

#define SERVO_HZ_MAX 330
#define SERVO_PERIOD_MIN_NS 500
#define SERVO_PERIOD_MAX_NS 2500
#define SERVO_MAX_ANGLE 180

static inline Servo servo_init(uint pin) { return pwm(pin, SERVO_HZ_MAX); }

#define SERVO_0_DEG_DUTY_CYCLE_S 0.0007
#define SERVO_180_DEG_DUTY_CYCLE_S 0.0023
#define SERVO_RANGE_DEG 180

static inline void servo_set(Servo x, uint16_t deg) {
  const uint32_t core_clk_hz = clock_get_hz(clk_sys);
  float duty_cycle = ( (((float) deg) / SERVO_RANGE_DEG) * (SERVO_180_DEG_DUTY_CYCLE_S - SERVO_0_DEG_DUTY_CYCLE_S) ) + SERVO_0_DEG_DUTY_CYCLE_S;
  uint16_t duty_cycle_ticks = (uint16_t) (duty_cycle * (((float) core_clk_hz) / SERVO_CLK_DIV));
  pwm_set_chan_level(x.slice, x.channel, duty_cycle_ticks);
}

static inline void servo_idle(Servo x) { pwm_set_chan_level(x.slice, x.channel, 0); }

static const struct LegServoPins {
  uint8_t rightFront[3];
  uint8_t rightBack[3];
  uint8_t leftFront[3];
  uint8_t leftBack[3];
} LegServoPins = {{4, 5, 6}, {7, 8, 9}, {15, 16, 17}, {18, 19, 20}};

typedef struct LegServos {
  Servo rightFront[3];
  Servo rightBack[3];
  Servo leftFront[3];
  Servo leftBack[3];
} LegServos;

static inline LegServos leg_servo_init() {
  LegServos l;
  for (int i = 0; i < 3; ++i) {
    l.rightFront[i] = servo_init(LegServoPins.rightFront[i]);
    servo_idle(l.rightFront[i]);
  }
  for (int i = 0; i < 3; ++i) {
    l.rightBack[i] = servo_init(LegServoPins.rightBack[i]);
    servo_idle(l.rightBack[i]);
  }
  for (int i = 0; i < 3; ++i) {
    l.leftFront[i] = servo_init(LegServoPins.leftFront[i]);
    servo_idle(l.leftFront[i]);
  }
  for (int i = 0; i < 3; ++i) {
    l.leftBack[i] = servo_init(LegServoPins.leftBack[i]);
    servo_idle(l.leftBack[i]);
  }
  return l;
}
