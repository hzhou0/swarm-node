<template>
  <v-window-item value="Stream">
    <v-row class="align-center">
      <v-col cols="8">
        <v-select
          label="Audio Output"
          hide-details
          :loading="f.data.audioDevices === undefined"
          :items="f.data.audioDevices?.filter((d) => d.type === 'sink')"
          :item-props="
            (item: AudioDevice) => ({
              title: item.description,
              subtitle: item.name,
              form_factor: item.form_factor,
            })
          "
          @update:model-value="(v) => (audioOutputName = v.name)"
        >
          <template #item="{ props }">
            <v-list-item
              v-bind="props"
              :append-icon="formfactorIcons.get(props.form_factor)"
            ></v-list-item>
          </template>
        </v-select>
      </v-col>
      <v-col>
        <v-slider
          min="0"
          max="1"
          step="0.01"
          :prepend-icon="
            audioOutput?.mute ? 'mdi-volume-mute' : 'mdi-volume-source'
          "
          thumb-label
          hide-details
          :model-value="audioOutput?.volume"
          @click:prepend="
            () => {
              if (audioOutput != null) {
                audioOutput = { ...audioOutput, mute: !audioOutput.mute };
              }
            }
          "
        ></v-slider>
      </v-col>
    </v-row>
    <v-row class="align-center">
      <v-col cols="8">
        <v-select
          label="Audio Input"
          hide-details
          :loading="f.data.audioDevices === undefined"
          :items="f.data.audioDevices?.filter((d) => d.type === 'source')"
          :item-props="
            (item: AudioDevice) => ({
              title: item.description,
              subtitle: item.name,
              form_factor: item.form_factor,
            })
          "
          @update:model-value="(v) => (audioInputName = v.name)"
        >
          <template #item="{ props }">
            <v-list-item
              v-bind="props"
              :append-icon="formfactorIcons.get(props.form_factor)"
            ></v-list-item>
          </template>
        </v-select>
      </v-col>
      <v-col>
        <v-slider
          min="0"
          max="1"
          step="0.01"
          :prepend-icon="
            audioInput?.mute ? 'mdi-volume-mute' : 'mdi-volume-source'
          "
          thumb-label
          hide-details
          :model-value="audioInput?.volume"
          @click:prepend="
            () => {
              if (audioInput != null) {
                audioInput = { ...audioInput, mute: !audioInput.mute };
              }
            }
          "
        ></v-slider>
      </v-col>
    </v-row>
    <v-row>
      <v-divider></v-divider>
    </v-row>
    <v-row>
      <v-col>
        <v-select
          v-model="videoInput"
          label="Video Device"
          hide-details
          :loading="f.data.videoDevices === undefined"
          :items="f.data.videoDevices"
          :item-props="
            (item: AudioDevice) => ({
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
import { AudioDevice, VideoDevice, VideoSize, VideoStream } from "@/sdk";

const f = new Fetcher(
  {
    audioStream: () => client.audioStreamInfo(),
    videoStream: () => client.videoStreamInfo(),
    audioDevices: () => client.listAudioDevices(),
    videoDevices: () => client.listVideoDevices(),
  },
  1000,
);

const audioOutputName: Ref<string | null> = ref(null);
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
const audioInputName: Ref<string | null> = ref(null);
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
type VideoSetting = Partial<Omit<VideoStream, "name">>;
const videoSettings: Ref<Record<string, VideoSetting>> = ref({});
watchEffect(() => {
  if (f.data.videoDevices) {
    for (const d of f.data.videoDevices) {
      videoSettings.value[d.name] ??= {};
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
    acc = acc.filter((size) => size.fps.includes(setOptions.fps));
  }
  if (setOptions.height != null && option != "height") {
    acc = acc.filter((size) => size.height == setOptions.height);
  }
  if (setOptions.width != null && option != "width") {
    acc = acc.filter((size) => size.width == setOptions.width);
  }
  return dedupe(acc.map((size) => size[option]));
}

const formfactorIcons: Map<AudioDevice["form_factor"], string> = new Map([
  ["car", "mdi-car"],
  ["computer", "mdi-desktop"],
  ["hands-free", "mdi-headset"],
  ["handset", "mdi-phone-classic"],
  ["headphone", "mdi-headphones"],
  ["headset", "mdi-headset"],
  ["hifi", "mdi-speaker-multiple"],
  ["internal", "mdi-monitor-speaker"],
  ["microphone", "mdi-microphone"],
  ["portable", "mdi-cellphone-sound"],
  ["speaker", "mdi-speaker"],
  ["tv", "mdi-television-speaker"],
  ["webcam", "mdi-webcam"],
  [null, "mdi-help-circle-outline"],
]);
</script>
