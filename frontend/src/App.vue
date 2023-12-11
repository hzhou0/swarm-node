<template>
  <v-app>
    <v-main>
      <v-app-bar density="compact">
        <v-app-bar-nav-icon @click="showControlPanel = !showControlPanel"></v-app-bar-nav-icon>
        <v-app-bar-title v-if="!mobile">Control Panel</v-app-bar-title>
        <v-spacer></v-spacer>
        <v-btn @click="streamStore?.dataChannel?.send('hi there')">Send datachannel</v-btn>
        <template v-if="mobile" #extension>
          <v-btn-toggle
            :model-value="streamStatus"
            style="pointer-events: none"
            multiple
            rounded="0"
            color="success"
            class="flex-wrap pa-2"
          >
            <v-btn v-for="name in streamStatusMembers" :key="name" size="x-small">{{ name }}</v-btn>
          </v-btn-toggle>
        </template>
        <v-btn-toggle
          v-if="!mobile"
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
        <v-row class="fill-height">
          <v-slide-x-transition>
            <v-col v-if="showControlPanel" lg="4" sm="12">
              <ControlPanel></ControlPanel>
            </v-col>
          </v-slide-x-transition>
          <v-col>
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
import { computed, ref } from "vue";
import { useDisplay } from "vuetify";

const showControlPanel = ref(true);
const { mobile } = useDisplay();

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
