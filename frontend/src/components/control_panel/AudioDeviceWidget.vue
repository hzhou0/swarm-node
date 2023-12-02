<template>
  <v-row class="align-center">
    <v-col cols="8">
      <v-select
        :model-value="selectedDevice"
        :label="label"
        variant="outlined"
        :prepend-inner-icon="formFactorIcons.get(selectedDevice?.form_factor)"
        hide-details
        :loading="devices == undefined"
        :items="devices"
        :item-props="
          (item: AudioDevice) => ({
            title: item.description,
            subtitle: item.name,
            form_factor: item.form_factor,
          })
        "
        @update:model-value="(v) => $emit('update:selectedDeviceName', v.name)"
      >
        <template #item="{ props }">
          <v-list-item
            v-bind="props"
            :prepend-icon="formFactorIcons.get(props.form_factor as AudioDevice['form_factor'])"
          ></v-list-item>
        </template>
      </v-select>
    </v-col>
    <v-col>
      <v-checkbox-btn
        :model-value="selectedDevice?.default"
        label="Default"
        :disabled="selectedDevice?.default"
        @update:model-value="
          (value) => {
            if (selectedDevice != null) {
              $emit('update:selectedDevice', {
                ...selectedDevice,
                default: value,
              });
            }
          }
        "
      ></v-checkbox-btn>
    </v-col>
    <v-col cols="12">
      <v-slider
        min="0"
        max="1"
        step="0.01"
        :prepend-icon="selectedDevice?.mute ? 'mdi-volume-mute' : 'mdi-volume-source'"
        thumb-label
        hide-details
        :model-value="selectedDevice?.volume"
        @click:prepend="
          () => {
            if (selectedDevice != null) {
              $emit('update:selectedDevice', {
                ...selectedDevice,
                mute: !selectedDevice.mute,
              });
            }
          }
        "
        @update:model-value="
          (v) => {
            if (selectedDevice != null) {
              $emit('update:selectedDevice', {
                ...selectedDevice,
                volume: v,
              });
            }
          }
        "
      >
        <template #append>
          <v-text-field
            :model-value="selectedDevice?.volume.toFixed(2)"
            type="number"
            style="max-width: 7.25rem"
            density="compact"
            hide-details
            hide-spin-buttons
            variant="outlined"
            prepend-inner-icon="mdi-minus"
            append-inner-icon="mdi-plus"
            readonly
            @click:prepend-inner="
              () => {
                if (selectedDevice != null) {
                  $emit('update:selectedDevice', {
                    ...selectedDevice,
                    volume: selectedDevice?.volume - 0.01,
                  });
                }
              }
            "
            @click:append-inner="
              () => {
                if (selectedDevice != null) {
                  $emit('update:selectedDevice', {
                    ...selectedDevice,
                    volume: selectedDevice?.volume + 0.01,
                  });
                }
              }
            "
          ></v-text-field>
        </template>
      </v-slider>
    </v-col>
  </v-row>
</template>
<script setup lang="ts">
import { AudioDevice } from "@/models";

defineProps<{
  selectedDevice: AudioDevice | null | undefined;
  selectedDeviceName: string | undefined;
  devices: AudioDevice[] | undefined;
  label: string;
}>();
defineEmits<{
  (e: "update:selectedDeviceName"): string;
  (e: "update:selectedDevice"): AudioDevice;
}>();

const formFactorIcons: Map<AudioDevice["form_factor"] | null | undefined, string> = new Map([
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
  [undefined, "mdi-help-circle-outline"],
]);
</script>
