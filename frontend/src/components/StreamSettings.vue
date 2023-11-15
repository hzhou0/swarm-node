<template>
  <v-window-item value="Stream">
    <AudioDeviceWidget
      v-model:selected-device="audioOutput"
      v-model:selected-device-name="audioOutputName"
      label="Audio Output"
      :devices="f.data.audioDevices?.filter((d) => d.type === 'sink')"
    />
    <AudioDeviceWidget
      v-model:selected-device="audioInput"
      v-model:selected-device-name="audioInputName"
      label="Audio Input"
      :devices="f.data.audioDevices?.filter((d) => d.type === 'source')"
    />
    <v-row>
      <v-divider></v-divider>
    </v-row>
    <v-row>
      <v-col>
        <v-select
          v-model="videoInput"
          label="Video Device"
          variant="outlined"
          prepend-inner-icon="mdi-video"
          hide-details
          :loading="f.data.videoDevices === undefined"
          :items="f.data.videoDevices"
          :item-props="
            (item) => ({
              title: item.description,
              subtitle: item.name,
            })
          "
        ></v-select>
      </v-col>
    </v-row>
    <v-row v-if="videoInput">
      <v-col>
        <v-select
          v-model="videoSettings[videoInput.name].format"
          label="Format"
          hide-details
          variant="outlined"
          :items="
            filterVideoSettings(
              videoInput.video_sizes,
              videoSettings[videoInput.name],
              'format',
            ).toSorted()
          "
        ></v-select>
      </v-col>
      <v-col>
        <v-select
          v-model="videoSettings[videoInput.name].fps"
          label="FPS"
          hide-details
          variant="outlined"
          clearable
          :items="
            dedupe(
              filterVideoSettings(
                videoInput.video_sizes,
                videoSettings[videoInput.name],
                'fps',
              ).flat(),
            )
          "
        ></v-select>
      </v-col>
      <v-col>
        <v-select
          v-model="videoSettings[videoInput.name].width"
          label="Width"
          hide-details
          variant="outlined"
          clearable
          :items="
            filterVideoSettings(
              videoInput.video_sizes,
              videoSettings[videoInput.name],
              'width',
            ).toSorted((a, b) => b - a)
          "
        ></v-select>
      </v-col>
      <v-col>
        <v-select
          v-model="videoSettings[videoInput.name].height"
          label="Height"
          hide-details
          variant="outlined"
          clearable
          :items="
            filterVideoSettings(
              videoInput.video_sizes,
              videoSettings[videoInput.name],
              'height',
            ).toSorted((a, b) => b - a)
          "
        ></v-select>
      </v-col>
    </v-row>
  </v-window-item>
</template>

<script setup lang="ts">
import { computed, Ref, ref, watchEffect } from "vue";
import { client, dedupe, Fetcher } from "@/util";
import { VideoDevice, VideoSize, VideoStream } from "@/sdk";
import AudioDeviceWidget from "@/components/AudioDeviceWidget.vue";
import { useStorageAsync } from "@vueuse/core";

const f = new Fetcher(
  {
    audioStream: () => client.audioStreamInfo(),
    videoStream: () => client.videoStreamInfo(),
    audioDevices: () => client.listAudioDevices(),
    videoDevices: () => client.listVideoDevices(),
  },
  5000,
);

const audioOutputName: Ref<string | undefined> = ref(undefined);
const audioOutput = computed({
  get() {
    return f.data.audioDevices?.find((v) => v.name == audioOutputName.value);
  },
  async set(val) {
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
  },
});
const audioInputName: Ref<string | undefined> = ref(undefined);
const audioInput = computed({
  get() {
    return f.data.audioDevices?.find((v) => v.name == audioInputName.value);
  },
  async set(val) {
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
  },
});
const videoInput: Ref<VideoDevice | null> = ref(null);
const preferredVideoInput: Ref<string | null> = useStorageAsync(
  "preferredVideoInput",
  null,
);
type VideoSetting = Partial<Omit<VideoStream, "name">>;
const videoSettings: Ref<Record<string, VideoSetting>> = useStorageAsync(
  "videoSettings",
  {},
);

watchEffect(() => {
  if (f.data.videoDevices) {
    for (const d of f.data.videoDevices) {
      videoSettings.value[d.name] ??= {};
      if (videoInput.value == null && d.name == preferredVideoInput.value) {
        videoInput.value = d;
      }
    }
  }
});

watchEffect(() => {
  if (
    videoInput.value != null &&
    videoInput.value?.name != preferredVideoInput.value
  ) {
    preferredVideoInput.value = videoInput.value?.name;
  }
});

watchEffect(() => {
  if (f.data.audioDevices) {
    if (audioOutputName.value == null) {
      audioOutputName.value = f.data.audioDevices.find(
        (v) => v.type == "sink" && v.default,
      )?.name;
    }
    if (audioInputName.value == null) {
      audioInputName.value = f.data.audioDevices.find(
        (v) => v.type == "source" && v.default,
      )?.name;
    }
  }
});
function filterVideoSettings<T extends keyof VideoSetting>(
  sizes: VideoSize[],
  setOptions: VideoSetting,
  option: T,
) {
  let acc = sizes;
  if (setOptions.format != null && option != "format") {
    acc = acc.filter((size) => size.format == setOptions.format);
  }
  if (setOptions.fps != null && option != "fps") {
    acc = acc.filter((size) => size.fps.includes(setOptions.fps as number));
  }
  if (setOptions.height != null && option != "height") {
    acc = acc.filter((size) => size.height == setOptions.height);
  }
  if (setOptions.width != null && option != "width") {
    acc = acc.filter((size) => size.width == setOptions.width);
  }
  return dedupe(acc.map((size) => size[option]));
}
</script>
