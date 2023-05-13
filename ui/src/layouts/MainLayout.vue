<template>
  <q-layout view="hHh LpR fFf">
    <q-header bordered class="bg-dark">
      <q-toolbar class="row no-wrap justify-between">
        <div class="col">
          <q-btn
            round
            flat
            icon="menu"
            color="secondary"
            @click="leftDrawerOpen = !leftDrawerOpen"
          />
          <DeviceSelector />
        </div>
        <div class="col-auto flex justify-center items-center">
          <q-btn-dropdown
            :loading="store.mode == null"
            :icon="dropdown.icon"
            :label="store.mode"
            :color="dropdown.color"
          >
          </q-btn-dropdown>
        </div>
        <div class="col flex justify-end items-center">
          <q-btn
            round
            flat
            icon="menu"
            color="secondary"
            @click="rightDrawerOpen = !rightDrawerOpen"
          />
        </div>
      </q-toolbar>
    </q-header>

    <q-drawer v-model="leftDrawerOpen" show-if-above side="left" dark>
      <!-- drawer content -->
    </q-drawer>

    <q-drawer v-model="rightDrawerOpen" show-if-above side="right">
      <!-- drawer content -->
    </q-drawer>

    <q-page-container>
      <router-view />
    </q-page-container>

    <q-footer bordered class="bg-dark">
      <q-toolbar>
        <q-toolbar-title>Title</q-toolbar-title>
      </q-toolbar>
    </q-footer>
  </q-layout>
</template>

<script setup>
import { computed, ref } from "vue";
import { store } from "../main";
import DeviceSelector from "../components/DeviceSelector.vue";

const leftDrawerOpen = ref(false);
const rightDrawerOpen = ref(false);

const dropdowns = {
  SAFE: {
    icon: "lock",
    color: "positive",
  },
  MANUAL: {
    icon: "lock_open",
    color: "warning",
  },
  null: {
    color: "info",
  },
};
const dropdown = computed(() => dropdowns[store.mode]);
</script>
