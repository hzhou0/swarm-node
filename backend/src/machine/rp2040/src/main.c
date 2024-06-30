/**
Using GTK+ convention:
- All macros and constants in caps: MAX_BUFFER_SIZE, TRACKING_ID_PREFIX.
- Struct names and typedef's in camelcase: GtkWidget, TrackingOrder.
- Functions that operate on structs: classic C style: gtk_widget_show(),
tracking_order_process().
- Pointers: nothing fancy here: GtkWidget *foo, TrackingOrder *bar.
- Global variables: just don't use global variables. They are evil.
 */
#include "gpi.h"
#include "i2c.h"
#include "io.h"
#include "pico/stdlib.h"
#include "servo.h"

INA226 current_sensor;
State state;

void gpio_callback(uint gpio, uint32_t event_masks) {
  ina226_alert_irq_handler(current_sensor, gpio, &state.current_sensor);
}

int main() {
  stdio_init_all();
  gpio_set_irq_callback(&gpio_callback);
  irq_set_enabled(IO_IRQ_BANK0, true);

  I2CBus bus0 = i2c_bus(i2c0, 1, 0, I2C_SPEED_FAST);
  I2CBus bus1 = i2c_bus(i2c1, 3, 2, I2C_SPEED_STD);

  ServoDegreesMutation sd_mut;
  LegServos leg_servos = leg_servo_init();
  current_sensor = ina226(bus0, 0b1000000, 12, 20 * 1000 * 1000, 2 * 1000);
  ina226_configure(current_sensor, INA226_CONFIG_AVG_1, INA226_CONFIG_CT_1100us,
                   INA226_CONFIG_CT_1100us,
                   INA226_CONFIG_MODE_BUS_SHUNT_CONTINUOUS);
  ina226_enable_alert(current_sensor, INA226_ALERT_READY | INA226_ALERT_LATCH,
                      0, 0, 0);
  gpi_init();
  while (true) {
    state.gpi = gpi_get();
    process_commands(&sd_mut, &state);
  }
}
