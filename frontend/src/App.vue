<template>
  <v-app>
    <v-main>
      <v-row class="fill-height" no-gutters>
        <v-col>
          <ControlPanel></ControlPanel>
        </v-col>
        <v-col cols="8">
          <Stream />
        </v-col>
      </v-row>
    </v-main>
  </v-app>
</template>
<script setup lang="ts">
import Stream from "@/components/Stream.vue";
import ControlPanel from "@/components/ControlPanel/ControlPanel.vue";
</script>
