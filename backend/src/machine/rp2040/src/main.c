/**
Using GTK+ convention:
- All macros and constants in caps: MAX_BUFFER_SIZE, TRACKING_ID_PREFIX.
- Struct names and typedef's in camelcase: GtkWidget, TrackingOrder.
- Functions that operate on structs: classic C style: gtk_widget_show(),
tracking_order_process().
- Pointers: nothing fancy here: GtkWidget *foo, TrackingOrder *bar.
- Global variables: just don't use global variables. They are evil.
 */
#define PICO_STDIO_USB_CONNECT_WAIT_TIMEOUT_MS 10000

#include "io.h"
#include "pico/stdlib.h"

int main() {
  set_sys_clock_khz(250000, true);
  stdio_init_all();
  ServoDegreesMutation sd_mut;
  while (true) {
    processCommands(&sd_mut);
  }
}
