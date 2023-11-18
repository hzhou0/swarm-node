<template>
  <v-card>
    <div class="ma-4">
      <audio :autoplay="true"></audio>
      <video ref="video" :autoplay="true" :playsinline="true"></video>
    </div>
    <v-card-actions>
      <v-btn @click="start">Start</v-btn>
      <v-btn @click="stop">Stop</v-btn>
    </v-card-actions>
  </v-card>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { client } from "@/util";
import { storeToRefs } from "pinia";
import { useStreamStore } from "@/components/ControlPanel/store";
const { videoStreamSettings } = storeToRefs(useStreamStore());

const pc = new RTCPeerConnection({
  iceServers: [{ urls: ["stun:stun.l.google.com:19302"] }],
});
const video = ref<HTMLVideoElement | null>(null);
pc.addEventListener("track", (evt) => {
  if (evt.track.kind == "video" && video.value) {
    video.value.srcObject = evt.streams[0];
  }
});

async function negotiate() {
  pc.addTransceiver("video", { direction: "recvonly" });
  pc.addTransceiver("audio", { direction: "recvonly" });
  try {
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    if (pc.iceGatheringState !== "complete") {
      await new Promise((resolve) => {
        const checkState = () => {
          if (pc.iceGatheringState === "complete") {
            console.log("done");
            pc.removeEventListener("icegatheringstatechange", checkState);
            resolve(null);
          }
        };
        pc.addEventListener("icegatheringstatechange", checkState);
      });
    }
    const answer = await client.webrtcOffer({
      sdp: offer.sdp as string,
      type: offer.type,
    });
    return pc.setRemoteDescription(answer);
  } catch (e) {
    alert(e);
  }
}

async function start() {
  if (!videoStreamSettings.value) {
    return;
  }
  await client.startVideoStream(videoStreamSettings.value);
  await negotiate();
}

async function stop() {
  // close peer connection
  setTimeout(function () {
    pc.close();
  }, 500);
  await client.stopVideoStream();
}
</script>
