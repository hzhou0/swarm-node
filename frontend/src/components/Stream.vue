<template>
  <v-card>
    <v-row justify="center">
      <v-col cols="auto">
        <audio ref="audio" :autoplay="true"></audio>
        <video
          ref="video"
          :autoplay="true"
          :playsinline="true"
          style="max-width: 100%; max-height: 100%"
        ></video>
      </v-col>
    </v-row>
    <v-card-actions>
      <v-btn
        v-if="stream.tracks.machineAudio == null && stream.tracks.machineVideo == null"
        prepend-icon="mdi-play"
        @click="stream.negotiate(true, true)"
      >
        Connect
      </v-btn>
      <v-btn v-else prepend-icon="mdi-stop" @click="stopMediaStreams">Disconnect</v-btn>
      <v-slider
        v-model="playerState.volume"
        min="0"
        max="1"
        step="0.01"
        :prepend-icon="playerState.mute ? 'mdi-volume-mute' : 'mdi-volume-source'"
        hide-details
        style="max-width: 20%"
        @click:prepend="playerState.mute = !playerState.mute"
      ></v-slider>
      <v-spacer></v-spacer>
      <v-btn-toggle v-model="videoUIMode" mandatory>
        <v-btn icon="mdi-video"></v-btn>
        <v-btn icon="mdi-console"></v-btn>
        <v-btn icon="mdi-information"></v-btn>
      </v-btn-toggle>
    </v-card-actions>
    <InfoPane v-if="videoUIMode == 2" :model-value="stream.pcStats"></InfoPane>
  </v-card>
</template>
<script setup lang="ts">
import { ref, watch, watchEffect } from "vue";
import InfoPane from "@/components/InfoPane.vue";
import { useStreamStore } from "@/store/stream";

const stream = useStreamStore();

const video = ref<HTMLAudioElement | null>(null);
const audio = ref<HTMLVideoElement | null>(null);
const playerState = ref({
  mute: false,
  volume: 1,
});
watchEffect(() => {
  if (audio.value) {
    audio.value.muted = playerState.value.mute;
    audio.value.volume = playerState.value.volume;
  }
});
watch(stream.tracks, (val) => {
  if (video.value) {
    video.value.srcObject = val.machineVideo;
  }
  if (audio.value) {
    audio.value.srcObject = val.machineAudio;
  }
});
function stopMediaStreams() {
  stream.negotiate(false, false);
  if (video.value) {
    video.value.srcObject = null;
  }
  if (audio.value) {
    audio.value.srcObject = null;
  }
}
const videoUIMode = ref(0);
</script>
