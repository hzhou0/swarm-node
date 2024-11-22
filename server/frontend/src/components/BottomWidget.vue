<template>
  <v-container style="bottom: 0; position: fixed; z-index: 1004; left: 0" class="ma-0 pa-0" fluid>
    <v-card tile style="display: flex" color="surface1">
      <v-card-text v-if="bottomWindow === 'System Perf'">
        <v-row>
          <v-col cols="auto">
            <v-btn readonly>
              CPU Freq
              <v-chip class="ml-2">
                {{
                  perfFetcher.data.sysPerf?.cpu_freq_mhz
                    ? (perfFetcher.data.sysPerf.cpu_freq_mhz / 1000).toFixed(2)
                    : null
                }}
                GHZ
              </v-chip>
            </v-btn>
          </v-col>
          <v-col cols="auto">
            <v-btn readonly>
              Average Load/Core
              <v-chip class="ml-2">
                {{ perfFetcher.data.sysPerf?.cpu_load_avg_per_core_percent.toFixed(2) }}
                %
              </v-chip>
            </v-btn>
          </v-col>
          <v-col cols="auto">
            <v-btn readonly>
              CPU Usage
              <v-chip class="ml-2">
                {{ perfFetcher.data.sysPerf?.cpu_percent.toFixed(2) }}
                %
              </v-chip>
            </v-btn>
          </v-col>
          <v-col cols="auto">
            <v-btn readonly>
              Free Memory
              <v-chip class="ml-2">
                {{
                  perfFetcher.data.sysPerf?.mem_available_bytes
                    ? (perfFetcher.data.sysPerf?.mem_available_bytes / 1e9).toFixed(2)
                    : null
                }}
                GB
              </v-chip>
            </v-btn>
          </v-col>
          <v-col cols="auto">
            <v-btn readonly>
              Free Disk
              <v-chip class="ml-2">
                {{
                  perfFetcher.data.sysPerf?.disk_free_bytes
                    ? (perfFetcher.data.sysPerf?.disk_free_bytes / 1e9).toFixed(2)
                    : null
                }}
                GB
              </v-chip>
            </v-btn>
          </v-col>
        </v-row>
      </v-card-text>
      <v-card-text v-else-if="bottomWindow === 'Processes Perf'">
        <v-row>
          <v-col cols="auto">
            <v-btn readonly>
              Core #
              <v-chip class="ml-2">
                {{ perfFetcher.data.procPerf?.[selectedProc]?.cpu_num }}
              </v-chip>
            </v-btn>
          </v-col>
          <v-col cols="auto">
            <v-btn readonly>
              CPU Usage
              <v-chip class="ml-2">
                {{ perfFetcher.data.procPerf?.[selectedProc]?.cpu_percent }}
                %
              </v-chip>
            </v-btn>
          </v-col>
          <v-col cols="auto">
            <v-btn readonly>
              PSS Mem
              <v-chip class="ml-2">
                {{
                  perfFetcher.data.procPerf?.[selectedProc]
                    ? (perfFetcher.data.procPerf?.[selectedProc].mem_pss_bytes / 1e6).toFixed(2)
                    : null
                }}
                MB
              </v-chip>
            </v-btn>
          </v-col>
          <v-col cols="auto">
            <v-btn readonly>
              USS Mem
              <v-chip class="ml-2">
                {{
                  perfFetcher.data.procPerf?.[selectedProc]
                    ? (perfFetcher.data.procPerf?.[selectedProc].mem_uss_bytes / 1e6).toFixed(2)
                    : null
                }}
                MB
              </v-chip>
              <v-chip class="ml-2">
                {{ perfFetcher.data.procPerf?.[selectedProc].mem_uss_percent.toFixed(2) }}
                %
              </v-chip>
            </v-btn>
          </v-col>
          <v-col cols="auto">
            <v-btn readonly>
              Uptime
              <v-chip class="ml-2">
                {{
                  uptimeFromCreateTime(perfFetcher.data.procPerf?.[selectedProc].create_time_epoch)
                }}
              </v-chip>
            </v-btn>
          </v-col>
        </v-row>
        <v-row>
          <v-col>
            <v-sheet color="surface1">
              <v-slide-group
                v-model="selectedProc"
                show-arrows="always"
                selected-class="v-btn--active"
              >
                <v-slide-group-item
                  v-for="(_, k) in perfFetcher.data.procPerf"
                  :key="k"
                  v-slot="{ selectedClass, toggle }"
                  :value="k"
                >
                  <v-btn
                    :class="[selectedClass, 'ma-2']"
                    rounded
                    variant="outlined"
                    density="compact"
                    @click="toggle"
                    >{{ k }}
                  </v-btn>
                </v-slide-group-item>
              </v-slide-group>
            </v-sheet>
          </v-col>
        </v-row>
      </v-card-text>
    </v-card>
    <v-footer class="py-0 px-2">
      <v-item-group v-model="bottomWindow" selected-class="v-btn--active">
        <v-item v-for="(w, k) in windows" v-slot="{ toggle, selectedClass }" :key="k" :value="k">
          <v-btn :class="[selectedClass]" variant="flat" :prepend-icon="w.icon" @click="toggle">
            {{ k }}
          </v-btn>
        </v-item>
      </v-item-group>
      <v-spacer></v-spacer>
      <v-menu>
        <template #activator="{ props }">
          <v-btn variant="plain" v-bind="props" prepend-icon="mdi-menu-up"> API Docs</v-btn>
        </template>
        <v-list>
          <v-list-item
            v-for="uri in schemaEndpoints"
            :key="uri"
            append-icon="mdi-open-in-new"
            slim
            @click="openNewTab(uri)"
          >
            <v-list-item-title>{{ uri.split("/").at(-1) }}</v-list-item-title>
          </v-list-item>
        </v-list>
      </v-menu>
    </v-footer>
  </v-container>
</template>
<script setup lang="ts">
import * as sdk from "@/generated/sdk";
import { client, Fetcher } from "@/util";
import { useStorageAsync } from "@vueuse/core";
import { Ref, ref, watch } from "vue";
import { DateTime, Interval } from "luxon";

const bottomWindow = useStorageAsync("bottomWindow", "");
const selectedProc: Ref<string> = ref("");

const schemaEndpoints = [
  "/schema/swagger",
  "/schema/redoc",
  "/schema/elements",
  "/schema/rapidoc",
  "/schema/openapi.yaml",
  "/schema/openapi.json",
].map((url) => sdk.defaults.baseUrl + url);

const perfFetcher = new Fetcher(
  {
    sysPerf: () => client.getSystemPerformance(),
    procPerf: () => client.listProcessPerformance(),
  },
  500,
);
watch(perfFetcher.data, () => {
  if (!selectedProc.value && perfFetcher.data.procPerf) {
    selectedProc.value = Object.keys(perfFetcher.data.procPerf)[0];
  }
});

const windows = {
  "System Perf": { icon: "mdi-thermostat" },
  "Processes Perf": { icon: "mdi-thermostat-box" },
};

function uptimeFromCreateTime(createTimeEpoch: number | undefined) {
  if (createTimeEpoch == null) {
    return "unknown";
  }
  return Interval.fromDateTimes(DateTime.fromSeconds(createTimeEpoch), DateTime.now())
    .toDuration(["days", "hours"])
    .toHuman({ maximumFractionDigits: 1 });
}

function openNewTab(uri: string) {
  window.open(uri);
}
</script>
