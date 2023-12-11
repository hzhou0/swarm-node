<template>
  <v-row v-if="modelValue != null">
    <v-col cols="auto">
      <v-text-field
        v-model="search"
        label="Search"
        prepend-inner-icon="mdi-magnify"
        single-line
        variant="outlined"
        density="compact"
        class="pa-2"
        hide-details
      ></v-text-field>
      <v-tabs v-model="tab" direction="vertical">
        <v-tab v-for="(v, k) in props.modelValue" :key="k" :value="k" density="compact">{{
          k
        }}</v-tab>
      </v-tabs>
    </v-col>
    <v-col>
      <v-window v-model="tab">
        <v-window-item v-for="(v, k) in props.modelValue" :key="k" :value="k">
          <v-data-table
            density="compact"
            :sort-by="[{ key: k, order: 'asc' }]"
            :items="mapToList(v)"
            :headers="[
              { title: 'key', value: 'k', align: 'start', width: '30ch' },
              { title: 'value', value: 'v', align: 'end' },
            ]"
            items-per-page="6"
            :items-per-page-options="[3, 6, 12]"
            style="overflow-wrap: anywhere"
            :search="search"
          >
          </v-data-table>
        </v-window-item>
      </v-window>
    </v-col>
  </v-row>
</template>

<script setup lang="ts">
import { ref } from "vue";

type Map = Record<string, unknown>;
const props = defineProps<{ modelValue: Record<string, Map | undefined> | null }>();
const tab = ref(null);
const search = ref("");
function mapToList(map: Map | undefined) {
  if (map == undefined) {
    return [];
  }
  return Object.entries(map).map(([k, v]) => ({
    k,
    v,
  }));
}
</script>

<style scoped></style>
