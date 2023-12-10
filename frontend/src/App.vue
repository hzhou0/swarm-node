<template>
  <v-app>
    <v-main>
      <v-app-bar density="compact">
        <v-app-bar-nav-icon></v-app-bar-nav-icon>
        <v-app-bar-title>Control Panel</v-app-bar-title>
        <v-spacer></v-spacer>
        <v-btn @click="streamStore?.dataChannel?.send('hi there')">Send datachannel</v-btn>
        <v-btn-toggle
          variant="outlined"
          :model-value="streamStatus"
          class="mx-4"
          style="height: 40px; pointer-events: none"
          multiple
          divided
          color="success"
        >
          <v-btn v-for="name in streamStatusMembers" :key="name" size="small">{{ name }}</v-btn>
        </v-btn-toggle>
      </v-app-bar>
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
import { useStreamStore } from "@/store/stream";
import { computed } from "vue";

const streamStore = useStreamStore();
if (streamStore.pc == null) {
  streamStore.negotiate(false, false);
}
const streamStatusMembers = [
  "Client Audio",
  "Client Video",
  "Machine Audio",
  "Machine Video",
  "Data Channel",
] as const;
const streamStatus = computed(() => {
  const streamStatus: number[] = [];
  if (streamStore.pcStats == null) {
    return streamStatus;
  }
  if (streamStore.pcStats?.inbound_audio) {
    streamStatus.push(streamStatusMembers.indexOf("Machine Audio"));
  }
  if (streamStore.pcStats?.inbound_video) {
    streamStatus.push(streamStatusMembers.indexOf("Machine Video"));
  }
  if (streamStore.pcStats?.outbound_audio) {
    streamStatus.push(streamStatusMembers.indexOf("Client Audio"));
  }
  if (streamStore.pcStats?.outbound_video) {
    streamStatus.push(streamStatusMembers.indexOf("Client Video"));
  }
  if (streamStore.pcStats?.data_channel?.state == "open") {
    streamStatus.push(streamStatusMembers.indexOf("Data Channel"));
  }
  return streamStatus;
});
</script>
