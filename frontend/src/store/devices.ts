import { defineStore } from "pinia";
import { computed, ComputedRef, ref, Ref, watch } from "vue";
import { client, Fetcher } from "@/util";
import { AudioDevice, VideoDevice, VideoTrack } from "@/generated/models";
import { useStorageAsync } from "@vueuse/core/index";

export type VideoSetting = Partial<Omit<VideoTrack, "name">>;

export const useDeviceStore = defineStore("Device", () => {
  const f = new Fetcher(
    {
      audioDevices: () => client.listAudioDevices(),
      videoDevices: () => client.listVideoDevices(),
    },
    5000,
  );
  const data = f.data;
  async function setAudioDevice(val: AudioDevice | undefined) {
    if (val != null) {
      if (f.data.audioDevices != null) {
        const i = f.data.audioDevices.findIndex((v) => v.name == val.name);
        f.data.audioDevices[i] = val;
      }
      await client.putAudioDevice({
        volume: val.volume,
        name: val.name,
        default: val.default,
        mute: val.mute,
      });
    }
  }

  watch(f.data, ({ videoDevices, audioDevices }) => {
    if (audioDevices) {
      if (audioOutputName.value == null) {
        audioOutputName.value = audioDevices.find((v) => v.type == "sink" && v.default)?.name;
      }
      if (audioInputName.value == null) {
        audioInputName.value = audioDevices.find((v) => v.type == "source" && v.default)?.name;
      }
    }
    if (videoDevices) {
      for (const vd of videoDevices) {
        videoSettings.value[vd.name] ??= {};
        if (videoInput.value == null && vd.name == preferredVideoInput.value) {
          videoInput.value = vd;
        }
      }
    }
  });

  const audioOutputName: Ref<string | undefined> = ref(undefined);
  const audioOutput = computed({
    get() {
      return f.data.audioDevices?.find((v) => v.name == audioOutputName.value);
    },
    set: setAudioDevice,
  });
  const audioInputName: Ref<string | undefined> = ref(undefined);
  const audioInput = computed({
    get() {
      return f.data.audioDevices?.find((v) => v.name == audioInputName.value);
    },
    set: setAudioDevice,
  });
  const videoInput: Ref<VideoDevice | null> = ref(null);
  const preferredVideoInput: Ref<string | null> = useStorageAsync("preferredVideoInput", null);
  watch(videoInput, (v) => {
    if (v != null) {
      preferredVideoInput.value = v.name;
    }
  });
  const videoSettings: Ref<Record<string, VideoSetting>> = useStorageAsync("videoSettings", {});
  const videoTrackSettings: ComputedRef<VideoTrack | null> = computed(() => {
    if (videoInput.value == null || !(videoInput.value.name in videoSettings.value)) {
      return null;
    }
    const { fps, format, height, width } = videoSettings.value[videoInput.value.name];
    if (fps && format && height && width) {
      return { name: videoInput.value.name, fps, format, height, width };
    }
    return null;
  });
  return {
    data,
    audioOutputName,
    audioOutput,
    audioInputName,
    audioInput,
    videoInput,
    videoSettings,
    videoTrackSettings,
  };
});
