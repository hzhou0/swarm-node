<template>
  <v-app>
    <v-main>
      <v-system-bar window>
        <v-spacer></v-spacer>
        <v-icon icon="mdi-signal"></v-icon>
        <v-icon icon="mdi-signal-off"></v-icon>
      </v-system-bar>
      <v-container fluid>
        <v-row class="fill-height" no-gutters>
          <v-col>
            <ControlPanel></ControlPanel>
          </v-col>
          <v-col cols="8">
            <Stream />
          </v-col>
        </v-row>
      </v-container>
    </v-main>
  </v-app>
</template>
<script setup lang="ts">
import Stream from "@/components/Stream.vue";
import ControlPanel from "@/components/control_panel/ControlPanel.vue";
</script>
