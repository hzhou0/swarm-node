<template>
  <v-window-item value="Stream">
    <AudioDeviceWidget
      v-model:selected-device="audioOutput"
      v-model:selected-device-name="audioOutputName"
      label="Audio Output"
      :devices="data.audioDevices?.filter((d) => d.type === 'sink')"
    />
    <AudioDeviceWidget
      v-model:selected-device="audioInput"
      v-model:selected-device-name="audioInputName"
      label="Audio Input"
      :devices="data.audioDevices?.filter((d) => d.type === 'source')"
    />
    <v-row>
      <v-col>
        <v-select
          v-model="videoInput"
          label="Video Device"
          variant="outlined"
          prepend-inner-icon="mdi-video"
          hide-details
          :loading="data.videoDevices === undefined"
          :items="data.videoDevices"
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
import { dedupe } from "@/util";
import { VideoSize } from "@/sdk";
import AudioDeviceWidget from "./AudioDeviceWidget.vue";
import { VideoSetting, useStreamStore } from "./store";
import { storeToRefs } from "pinia";

const {
  data,
  audioInputName,
  audioOutputName,
  videoInput,
  videoSettings,
  audioInput,
  audioOutput,
} = storeToRefs(useStreamStore());

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
