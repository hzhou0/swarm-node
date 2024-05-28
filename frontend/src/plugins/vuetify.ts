/**
 * plugins/vuetify.ts
 *
 * Framework documentation: https://vuetifyjs.com`
 */

// Styles
import "@mdi/font/css/materialdesignicons.css";
import "vuetify/styles";

// Composables
import { createVuetify } from "vuetify";

// https://vuetifyjs.com/en/introduction/why-vuetify/#feature-guides
export default createVuetify({
  theme: {
    defaultTheme: "dark",
    themes: {
      dark: {
        dark: true,
        colors: {
          background: "#021a1e",
          surface: "#183539",
          surface1: "#283d3f",
          primary: "#f73c7d",
          secondary: "#4b9cbc",
          success: "#06c58b",
          info: "#5a586f",
          warning: "#dbda04",
          error: "#ed4702",
        },
      },
    },
  },
});
