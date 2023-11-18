/**
 * plugins/index.ts
 *
 * Automatically included in `./src/main.ts`
 */

// Plugins
import { loadFonts } from "./webfontloader";
import vuetify from "./vuetify";
import pinia from "@/plugins/pinia";
// Types
import type { App } from "vue";

export function registerPlugins(app: App) {
  void loadFonts();
  app.use(vuetify);
  app.use(pinia);
}
