import { reactive } from "vue";

export const store = reactive({
  coordinates: [null, null],
  mode: null,
  velocity: null,
  acceleration: [null, null, null],
  heading: null,
  epoch_time: null,
  battery_voltage: null,
  battery_percentage: null,
  mileage: null,
  failures: null,
  ultrasonic: [null, null, null, null],
});
