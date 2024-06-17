#ifndef LINE_FOLLOWING_PWM_H
#define LINE_FOLLOWING_PWM_H

#include "hardware/clocks.h"
#include "hardware/pwm.h"
#include "pico/stdlib.h"

typedef struct PWM {
  uint8_t slice;
  uint8_t channel;
} PWM;
typedef PWM Servo;

static inline PWM pwm(uint pin, float freqHz) {
  PWM pwm;
  gpio_set_function(pin, GPIO_FUNC_PWM);
  pwm.slice = pwm_gpio_to_slice_num(pin);
  pwm.channel = pwm_gpio_to_channel(pin);
  uint32_t core_clk_hz = clock_get_hz(clk_sys);
  pwm_set_clkdiv(pwm.slice, ((float)core_clk_hz) / freqHz / (float)(UINT16_MAX + 1));
  pwm_set_wrap(pwm.slice, UINT16_MAX);
  pwm_set_chan_level(pwm.slice, pwm.channel, 0);
  pwm_set_enabled(pwm.slice, true);
  return pwm;
}

void pwm_set(PWM x, uint16_t dutyCycle) {
  pwm_set_chan_level(x.slice, x.channel, dutyCycle);
}

#define SERVO_HZ_MAX 330
#define SERVO_PERIOD_MIN_NS 500
#define SERVO_PERIOD_MAX_NS 2500
#define SERVO_MAX_ANGLE 180

static inline Servo servo_init(uint pin) { return pwm(pin, SERVO_HZ_MAX); }

static inline void servo_set(Servo x, uint deg) {
  const uint SERVO_PERIOD_FULL_NS = 1000 * 1000 / SERVO_HZ_MAX;
  const uint MIN_SERVO_DUTY = ((UINT16_MAX + 1) * SERVO_PERIOD_MIN_NS / SERVO_PERIOD_FULL_NS);
  const uint MAX_SERVO_DUTY = ((UINT16_MAX + 1) * SERVO_PERIOD_MAX_NS / SERVO_PERIOD_FULL_NS);
  uint dutyCycle = deg * (MAX_SERVO_DUTY - MIN_SERVO_DUTY) / SERVO_MAX_ANGLE;
  pwm_set_chan_level(x.slice, x.channel, dutyCycle);
}

static inline void servo_idle(Servo x) {
  pwm_set_chan_level(x.slice, x.channel, 0);
}

static const struct LegServoPins {
  uint8_t rightFront[3];
  uint8_t rightBack[3];
  uint8_t leftFront[3];
  uint8_t leftBack[3];
} LegServoPins = {
	{4, 5, 6},
	{7, 8, 9},
	{15, 16, 17},
	{18, 19, 20}
};

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

#endif // LINE_FOLLOWING_PWM_H
