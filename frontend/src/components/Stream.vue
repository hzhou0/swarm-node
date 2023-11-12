<template>
  <v-card>
    <v-card-title> Hello there</v-card-title>
    <div class="ma-4">
      <audio id="audio" :autoplay="true"></audio>
      <video id="video" :autoplay="true" :playsinline="true"></video>
    </div>
    <v-card-actions>
      <v-btn>Start</v-btn>
      <v-btn>Stop</v-btn>
    </v-card-actions>
  </v-card>
</template>

<script setup lang="ts">
import { Ref, ref } from "vue";
import { client } from "@/util";
const config = {
  sdpSemantics: "unified-plan",
  iceServers: [{ urls: ["stun:stun.l.google.com:19302"] }],
};

const pc = new RTCPeerConnection(config);
const tracks: Ref<Record<string, MediaStream>> = ref({});

pc.addEventListener("track", (evt) => {
  tracks.value[evt.track.kind] = evt.streams[0];
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

function stop() {
  document.getElementById("stop").style.display = "none";

  // close peer connection
  setTimeout(function () {
    pc.close();
  }, 500);
}

//negotiate();
</script>
