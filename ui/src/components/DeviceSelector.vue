<template>
  <q-dialog v-model="deviceDeletion">
    <q-card>
      <q-card-section>
        <div class="text-h5">Permanently Deleting</div>
        <div class="text-subtitle1 text-primary">
          {{ deviceToDelete.toUpperCase() }}
        </div>
      </q-card-section>
      <q-card-actions align="right">
        <q-btn v-close-popup flat label="Cancel" color="info" />
        <q-btn
          v-close-popup
          flat
          label="Delete"
          color="negative"
          @click="removeDevice"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
  <q-btn-group flat class="q-mx-sm">
    <q-btn-dropdown
      outline
      color="primary"
      :label="deviceLabel"
      :disable="Object.keys(devices).length === 0"
    >
      <q-list bordered>
        <q-item
          v-for="(v, k) in devices"
          :key="k"
          v-close-popup
          clickable
          :active="device === k"
          active-class="text-primary"
          @click="device = k"
        >
          <q-item-section>
            <q-item-label>
              {{ k.toUpperCase() }}
            </q-item-label>
          </q-item-section>
          <q-item-section side>
            <q-btn
              v-close-popup="-1"
              color="negative"
              icon="delete_forever"
              dense
              @click.stop="
                deviceDeletion = true;
                deviceToDelete = k;
              "
            ></q-btn>
          </q-item-section>
        </q-item>
      </q-list>
    </q-btn-dropdown>
    <q-btn
      v-if="device !== null"
      dense
      outline
      color="primary"
      icon="close"
      @click="device = null"
    ></q-btn>
    <input
      ref="file"
      type="file"
      accept=".json"
      style="display: none"
      @input="addDevice"
    />
    <q-btn
      dense
      outline
      color="primary"
      icon="add"
      @click="$refs.file.click()"
    />
  </q-btn-group>

  <q-btn-dropdown
    :color="syncButtonProps.color"
    :icon="syncButtonProps.icon"
    :loading="syncButtonProps.loading"
    auto-close
  >
    <template #loading>
      <q-spinner-box></q-spinner-box>
    </template>
    <q-list bordered>
      <q-item-label v-if="googleToken" header>{{ userEmail }}</q-item-label>
      <q-separator v-if="googleToken"></q-separator>
      <q-item
        v-if="googleToken !== null"
        v-close-popup
        clickable
        @click="signOut"
      >
        <q-item-section avatar>
          <q-icon name="logout"></q-icon>
        </q-item-section>
        <q-item-section>Log Out</q-item-section>
      </q-item>
      <q-item v-else v-close-popup clickable @click="signIn">
        <q-item-section avatar>
          <q-icon name="login"></q-icon>
        </q-item-section>
        <q-item-section>Log In</q-item-section>
      </q-item>
      <q-separator></q-separator>
      <q-item v-close-popup clickable @click="downloadDevices">
        <q-item-section avatar>
          <q-icon name="download_for_offline"></q-icon>
        </q-item-section>
        <q-item-section>Export</q-item-section>
      </q-item>
    </q-list>
  </q-btn-dropdown>
</template>
<script setup>
import { computed, onMounted, ref } from "vue";
import { useQuasar } from "quasar";
import Ajv from "ajv/dist/jtd";
import axios from "axios";

const q = useQuasar();

/**
 * Parse device files to add new devices
 */
const device = ref(null);
const deviceDeletion = ref(false);
const deviceToDelete = ref("");
const deviceLabel = computed(() => {
  if (Object.keys(devices.value).length === 0) {
    return "No Devices";
  } else if (device.value === null) {
    return "None Selected";
  } else if (device.value.length > 28) {
    return device.value.substring(0, 28) + "..";
  }
  return device.value;
});
const devices = ref({});
let devices_rev = 0;
const ajv = new Ajv();

async function addDevice(event) {
  const deviceFile = event.target.files[0];
  event.target.value = null;
  const deviceSchema = {
    additionalProperties: true,
    properties: {
      name: {
        type: "string",
      },
      jwt: {
        type: "string",
      },
    },
  };
  const deviceParser = ajv.compileParser(deviceSchema);
  const deviceConfig = deviceParser(await deviceFile.text());
  if (deviceConfig === undefined) {
    q.notify({
      color: "negative",
      message: "Not a valid device file.",
      position: "top",
      actions: [{ icon: "close", color: "white" }],
    });
    return;
  }
  devices.value[deviceConfig.name] = deviceConfig.jwt;
  devices_rev++;
  await syncDevices();
}

async function removeDevice() {
  if (device.value === deviceToDelete.value) {
    device.value = null;
  }
  delete devices.value[deviceToDelete.value];
  deviceToDelete.value = "";
  devices_rev++;
  await syncDevices();
}

function downloadDevices() {
  const file = new Blob([JSON.stringify(devices.value)], {
    type: "application/json",
  });
  const a = document.createElement("a"),
    url = URL.createObjectURL(file);
  a.href = URL.createObjectURL(file);
  a.download = "devices.json";
  document.body.appendChild(a);
  a.click();
  setTimeout(function () {
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  }, 0);
}

/**
 * Google Drive synchronization
 */

let syncDaemon = false;

async function syncDevices() {
  if (
    googleToken.value === null ||
    googleToken.value.expires_at < Date.now() + 5000
  ) {
    googleToken.value = null;
    return;
  }
  const userInfo = await axios.get(
    `https://people.googleapis.com/v1/people/me`,
    {
      headers: {
        Authorization: `Bearer ${googleToken.value.access_token}`,
      },
      params: { personFields: "emailAddresses" },
    }
  );
  userEmail.value = userInfo.data.emailAddresses[0].value;

  const FILE_NAME = "7th-letter-robotics-devices.json";
  const gapi = axios.create({
    baseURL: "https://www.googleapis.com/",
    headers: { Authorization: `Bearer ${googleToken.value.access_token}` },
  });

  let { data } = await gapi.get(`drive/v3/files`, {
    params: { spaces: "appDataFolder", q: `name='${FILE_NAME}'` },
  });
  let remote_rev = -1;
  let remote_devices = {};
  if (data.files?.length) {
    const contents = await gapi.get(`drive/v3/files/${data.files[0].id}`, {
      params: {
        spaces: "appDataFolder",
        q: `name='${FILE_NAME}'`,
        alt: "media",
      },
    });
    if (Number.isInteger(contents.data._rev)) {
      remote_rev = contents.data._rev;
    }
    remote_devices = contents.data;
  } else {
    ({ data } = await gapi.post("drive/v3/files", {
      parents: ["appDataFolder"],
      name: FILE_NAME,
      mimeType: "application/json",
    }));
  }

  if (remote_rev < devices_rev) {
    await gapi.patch(
      `upload/drive/v3/files/${data.files[0].id}`,
      { ...devices.value, ...{ _rev: devices_rev } },
      {
        headers: { "Content-Type": "application/json" },
      }
    );
  } else {
    delete remote_devices._rev;
    devices_rev = remote_rev;
    devices.value = remote_devices;
  }
  if (!syncDaemon) {
    syncDaemon = true;
    setTimeout(syncDevices, 5000);
  }
}

const TOKEN_KEY = "gApiToken";
const googleIS = ref(null);
const userEmail = ref("");
const storedToken = JSON.parse(localStorage.getItem(TOKEN_KEY));
const googleToken = ref(
  (() => {
    if (storedToken == null || storedToken.expires_at < Date.now() + 5000) {
      return null;
    }
    return storedToken;
  })()
);
if (googleToken.value !== null) {
  syncDevices();
}

function signOut() {
  googleToken.value = null;
  localStorage.removeItem(TOKEN_KEY);
}

function signIn() {
  googleIS.value.requestAccessToken();
}

const CLIENT_ID =
  "134753770466-qamruq887sjcr7b8fm1booktebdu2p68.apps.googleusercontent.com";
const SCOPES =
  "https://www.googleapis.com/auth/drive.appdata " +
  "https://www.googleapis.com/auth/userinfo.profile " +
  "https://www.googleapis.com/auth/userinfo.email";
onMounted(() => {
  const gisScript = document.createElement("script");
  gisScript.src = "https://accounts.google.com/gsi/client";
  gisScript.type = "text/javascript";
  gisScript.addEventListener("load", (ev) => {
    googleIS.value = google.accounts.oauth2.initTokenClient({
      client_id: CLIENT_ID,
      scope: SCOPES,
      callback: (resp) => {
        googleToken.value = {
          ...resp,
          ...{ expires_at: Date.now() + resp.expires_in * 1000 },
        };
        localStorage.setItem(TOKEN_KEY, JSON.stringify(googleToken.value));
        syncDevices();
      },
    });

    if (storedToken && !googleToken.value) {
      googleIS.value.requestAccessToken({ prompt: "none" });
    }
  });
  document.body.appendChild(gisScript);
});
const syncButtonProps = computed(() => {
  if (googleIS.value === null) {
    return { color: "primary", icon: "", loading: true };
  } else if (googleToken.value === null) {
    return { color: "negative", icon: "sync_problem", loading: false };
  } else {
    return { color: "positive", icon: "cloud_sync", loading: false };
  }
});
</script>

<style scoped></style>
