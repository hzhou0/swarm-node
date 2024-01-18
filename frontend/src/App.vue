<template>
  <v-app>
    <v-main>
      <v-app-bar density="compact">
        <v-app-bar-nav-icon @click="showControlPanel = !showControlPanel"></v-app-bar-nav-icon>
        <v-app-bar-title v-if="!mobile">Control Panel</v-app-bar-title>
        <v-spacer></v-spacer>
        <v-text-field
          v-model="message"
          density="compact"
          hide-details
          append-inner-icon="mdi-send"
          @click:append-inner="streamStore?.dataChannel?.send(message + `;${Date.now() / 1000}`)"
        ></v-text-field>
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
        <v-row>
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
      <v-footer absolute app class="ma-0 pa-0">
        <v-spacer></v-spacer>
        <v-btn
          v-for="uri in schemaEndpoints"
          :key="uri"
          class="ma-1"
          variant="flat"
          size="x-small"
          append-icon="mdi-open-in-new"
          density="comfortable"
          @click="openNewTab(uri)"
          >{{ uri.split("/").at(-1) }}
        </v-btn>
      </v-footer>
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
const message = ref("hello world");
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

const schemaEndpoints = [
  "/schema/swagger",
  "/schema/redoc",
  "/schema/elements",
  "/schema/rapidoc",
  "/schema/openapi.yaml",
  "/schema/openapi.json",
];

function openNewTab(uri: string) {
  window.open(uri);
}
</script>
