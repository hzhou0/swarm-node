<template>
  <v-app>
    <v-main>
      <v-container fluid class="fill-height">
        <v-row class="fill-height">
          <v-col class="pa-0">
            <ControlPanel></ControlPanel>
          </v-col>
          <v-col class="pa-0" cols="6">
            <Stream />
          </v-col>
        </v-row>
      </v-container>
    </v-main>
  </v-app>
</template>
<script setup lang="ts">
import Stream from "@/components/Stream.vue";
import ControlPanel from "@/components/ControlPanel/ControlPanel.vue";
</script>
