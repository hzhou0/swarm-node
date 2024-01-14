import { defineStore, storeToRefs } from "pinia";
import { ref, shallowRef } from "vue";
import { client } from "@/util";
import { useDeviceStore } from "@/store/devices";

type InterfaceToType<T> = T extends object ? Pick<T, keyof T> : T;
type InterfaceToTypeDeep<T> = { [P in keyof T]: InterfaceToType<T[P]> };
interface RTCDataChannelStats extends RTCStats {
  label: string;
  protcol: string;
  dataChannelIdentifier: number;
  state: RTCDataChannelState;
  messagesSent: number;
  bytesSent: number;
  messagesReceived: number;
  bytesReceived: number;
}
type RTCPeerConnectionStats = InterfaceToTypeDeep<{
  transport?: RTCTransportStats;
  candidatePair?: RTCIceCandidatePairStats;
  inbound_video?: RTCInboundRtpStreamStats;
  inbound_audio?: RTCInboundRtpStreamStats;
  outbound_video?: RTCOutboundRtpStreamStats;
  outbound_audio?: RTCOutboundRtpStreamStats;
  data_channel?: RTCDataChannelStats;
  remote?: RTCIceCandidate;
}>;
type Tracks = {
  clientAudio: MediaStream | null;
  clientVideo: MediaStream | null;
  machineAudio: MediaStream | null;
  machineVideo: MediaStream | null;
};

export const useStreamStore = defineStore("Stream", () => {
  const { videoTrackSettings, audioOutputName } = storeToRefs(useDeviceStore());
  const pc = shallowRef<RTCPeerConnection | null>(null);
  const pcStats = shallowRef<RTCPeerConnectionStats | null>(null);
  const tracks = ref<Tracks>({
    clientAudio: null,
    clientVideo: null,
    machineAudio: null,
    machineVideo: null,
  });
  const dataChannel = shallowRef<RTCDataChannel | null>(null);

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
      } else if (s.type == "data-channel") {
        newStats.data_channel = s as RTCDataChannelStats;
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

    if (dataChannel.value == null) {
      return;
    }
  }, 1000);

  async function negotiate(machineAudio = false, machineVideo = false) {
    const newPC = new RTCPeerConnection({
      iceServers: [{ urls: ["stun:stun.l.google.com:19302"] }],
    });
    pc.value = newPC;

    dataChannel.value = null;
    const newDataChannel = newPC.createDataChannel("control", { ordered: false });
    newDataChannel.onopen = () => {
      dataChannel.value = newDataChannel;
    };

    tracks.value.machineAudio = null;
    tracks.value.machineVideo = null;
    newPC.addEventListener("track", (evt) => {
      if (evt.track.kind == "video" && machineVideo) {
        const videoOnly = new MediaStream();
        evt.streams[0].getVideoTracks().forEach((track) => {
          videoOnly.addTrack(track.clone());
        });
        tracks.value.machineVideo = videoOnly;
      } else if (evt.track.kind == "audio" && machineAudio) {
        const audioOnly = new MediaStream();
        evt.streams[0].getAudioTracks().forEach((track) => {
          audioOnly.addTrack(track.clone());
        });
        tracks.value.machineAudio = audioOnly;
      }
    });

    if (machineAudio) {
      if (tracks.value.clientAudio) {
        newPC.addTransceiver("audio", { direction: "sendrecv" });
      } else {
        newPC.addTransceiver("audio", { direction: "recvonly" });
      }
    } else if (tracks.value.clientAudio) {
      newPC.addTransceiver("audio", { direction: "sendonly" });
    }
    if (machineVideo) {
      if (tracks.value.clientVideo) {
        newPC.addTransceiver("video", { direction: "sendrecv" });
      } else {
        newPC.addTransceiver("video", { direction: "recvonly" });
      }
    } else if (tracks.value.clientVideo) {
      newPC.addTransceiver("video", { direction: "sendonly" });
    }
    try {
      const offer = await newPC.createOffer();
      await newPC.setLocalDescription(offer);
      let audioTrack = null;
      if (audioOutputName.value && machineAudio) {
        audioTrack = {
          name: audioOutputName.value,
        };
      }
      let videoTrack = null;
      if (machineVideo) {
        videoTrack = videoTrackSettings.value;
      }
      const answer = await client.webrtcOffer({
        sdp: offer.sdp as string,
        type: offer.type,
        tracks: {
          client_video: tracks.value.clientVideo != null,
          client_audio: tracks.value.clientAudio != null,
          machine_audio: audioTrack,
          machine_video: videoTrack,
        },
      });
      return newPC.setRemoteDescription(answer);
    } catch (e) {
      alert(e);
    }
  }

  async function stop() {
    pc.value?.close();
    pc.value = null;
    pcStats.value = null;
  }

  return { negotiate, stop, pc, pcStats, tracks, dataChannel };
});
