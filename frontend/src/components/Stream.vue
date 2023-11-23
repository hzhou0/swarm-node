<template>
  <v-card>
    <v-row justify="center">
      <v-col cols="auto">
        <audio :autoplay="true"></audio>
        <video
          ref="video"
          :autoplay="true"
          :playsinline="true"
          style="max-width: 100%; max-height: 100%"
        ></video>
      </v-col>
    </v-row>
    <v-card-actions>
      <v-btn v-if="pc == null" prepend-icon="mdi-play" @click="start">Connect</v-btn>
      <v-btn v-else prepend-icon="mdi-stop" @click="stop">Disconnect</v-btn>
      <v-spacer></v-spacer>
      <v-btn-toggle v-model="videoUIMode" mandatory>
        <v-btn icon="mdi-video"></v-btn>
        <v-btn icon="mdi-console"></v-btn>
        <v-btn icon="mdi-information"></v-btn>
      </v-btn-toggle>
    </v-card-actions>
    <InfoPane v-if="videoUIMode == 2" :model-value="pcStats"></InfoPane>
  </v-card>
</template>
<script setup lang="ts">
import { ref, shallowRef, ShallowRef } from "vue";
import { client } from "@/util";
import { storeToRefs } from "pinia";
import { useStreamStore } from "@/components/ControlPanel/store";
import InfoPane from "@/components/InfoPane.vue";

const { videoStreamSettings } = storeToRefs(useStreamStore());

const video = ref<HTMLVideoElement | null>(null);
const videoUIMode = ref(0);

const pc = shallowRef<RTCPeerConnection | null>(null);

type InterfaceToType<T> = T extends object ? Pick<T, keyof T> : T;
type InterfaceToTypeDeep<T> = { [P in keyof T]: InterfaceToType<T[P]> };
type RTCPeerConnectionStats = InterfaceToTypeDeep<{
  transport?: RTCTransportStats;
  candidatePair?: RTCIceCandidatePairStats;
  inbound_video?: RTCInboundRtpStreamStats;
  inbound_audio?: RTCInboundRtpStreamStats;
  outbound_video?: RTCOutboundRtpStreamStats;
  outbound_audio?: RTCOutboundRtpStreamStats;
  remote?: RTCIceCandidate;
}>;
const pcStats: ShallowRef<RTCPeerConnectionStats | null> = shallowRef(null);

setInterval(async () => {
  if (pc.value == null) {
    return;
  }
  const newStats: RTCPeerConnectionStats = {};
  const stats = (await pc.value.getStats()) as Map<
    string | undefined,
    NonNullable<RTCPeerConnectionStats[keyof RTCPeerConnectionStats]>
  >;
  stats.forEach((s) => {
    if (s.type == "transport") {
      newStats.transport = s as RTCTransportStats;
    } else if (s.type == "inbound-rtp" && "kind" in s && s.kind == "video") {
      newStats.inbound_video = s as RTCInboundRtpStreamStats;
    } else if (s.type == "inbound-rtp" && "kind" in s && s.kind == "audio") {
      newStats.inbound_audio = s as RTCInboundRtpStreamStats;
    } else if (s.type == "outbound-rtp" && "kind" in s && s.kind == "video") {
      newStats.outbound_video = s as RTCOutboundRtpStreamStats;
    } else if (s.type == "outbound-rtp" && "kind" in s && s.kind == "audio") {
      newStats.outbound_audio = s as RTCOutboundRtpStreamStats;
    }
  });
  const candidatePairId = newStats.transport?.selectedCandidatePairId;
  if (candidatePairId) {
    newStats.candidatePair = stats.get(candidatePairId) as RTCIceCandidatePairStats;
  }
  const remoteCandidateId = newStats.candidatePair?.remoteCandidateId;
  if (remoteCandidateId) {
    newStats.remote = stats.get(remoteCandidateId) as RTCIceCandidate;
  }
  pcStats.value = newStats;
}, 1000);

async function negotiate() {
  const newPC = new RTCPeerConnection({
    iceServers: [{ urls: ["stun:stun.l.google.com:19302"] }],
  });
  pc.value = newPC;
  newPC.addEventListener("track", (evt) => {
    if (evt.track.kind == "video" && video.value) {
      video.value.srcObject = evt.streams[0];
    }
  });
  newPC.addTransceiver("video", { direction: "recvonly" });
  newPC.addTransceiver("audio", { direction: "recvonly" });
  try {
    const offer = await newPC.createOffer();
    await newPC.setLocalDescription(offer);

    if (newPC.iceGatheringState !== "complete") {
      await new Promise((resolve) => {
        const checkState = () => {
          if (newPC.iceGatheringState === "complete") {
            newPC.removeEventListener("icegatheringstatechange", checkState);
            resolve(null);
          }
        };
        newPC.addEventListener("icegatheringstatechange", checkState);
      });
    }
    const answer = await client.webrtcOffer({
      sdp: offer.sdp as string,
      type: offer.type,
    });
    return newPC.setRemoteDescription(answer);
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
  pc.value?.close();
  pc.value = null;
  pcStats.value = null;
  //await client.stopVideoStream();
}
</script>
