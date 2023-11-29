<template>
  <v-card flat rounded density="compact">
    <v-tabs v-model="tabId">
      <v-tab v-for="tab in tabs" :key="tab" :value="tab">{{ tab }}</v-tab>
    </v-tabs>
    <v-window v-model="tabId" class="pt-4 px-2">
      <v-window-item value="Machine"></v-window-item>
      <StreamSettings />
      <v-window-item value="Map"></v-window-item>
    </v-window>
  </v-card>
</template>

<script setup lang="ts">
import { ref } from "vue";
import StreamSettings from "./StreamSettings.vue";

const tabs = ["Machine", "Map", "Stream"];
const tabId = ref("Stream");
</script>

<style scoped></style>
