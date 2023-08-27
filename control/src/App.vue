<template>
  <router-view />
</template>

<script>
import { publishOffer } from "../lib/webrtc/main";

publishOffer();
</script>
