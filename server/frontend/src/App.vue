<template>
  <v-app>
    <v-main>
      <v-app-bar density="compact">
        <template #prepend>
          <v-app-bar-nav-icon
            :icon="showControlPanel ? 'mdi-menu-open' : 'mdi-menu-close'"
            @click="showControlPanel = !showControlPanel"
          ></v-app-bar-nav-icon>
        </template>
        <v-app-bar-title>Control Panel</v-app-bar-title>
        <template #append>
          <div v-if="!mobile">
            <v-text-field
              v-model="message"
              density="compact"
              hide-details
              append-inner-icon="mdi-send"
              min-width="200px"
              @click:append-inner="
                streamStore?.dataChannel?.send(message + `;${Date.now() / 1000}`)
              "
            ></v-text-field>
          </div>
          <div v-if="mobile">
            <v-btn-toggle
              :model-value="streamStatus"
              style="pointer-events: none"
              multiple
              rounded="0"
              color="success"
              class="flex-wrap pa-2"
            >
              <v-btn v-for="name in streamStatusMembers" :key="name" size="x-small">{{
                name
              }}</v-btn>
            </v-btn-toggle>
          </div>
          <v-btn-toggle
            v-else
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
        </template>
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
      <bottom-widget />
    </v-main>
  </v-app>
</template>
<script setup lang="ts">
import Stream from "@/components/Stream.vue";
import ControlPanel from "@/components/control_panel/ControlPanel.vue";
import { useStreamStore } from "@/store/stream";
import { computed, ref } from "vue";
import { useDisplay } from "vuetify";
import BottomWidget from "@/components/BottomWidget.vue";

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
</script>
