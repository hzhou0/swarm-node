const ICE_SERVERS: Array<RTCIceServer> = [
  {
    urls: "stun:a.relay.metered.ca:80",
  },
  {
    urls: "turn:a.relay.metered.ca:80",
    username: "13f18f9bc955e70d76cc28e3",
    credential: "9PoAPBZesF9S1erU",
  },
  {
    urls: "turn:a.relay.metered.ca:80?transport=tcp",
    username: "13f18f9bc955e70d76cc28e3",
    credential: "9PoAPBZesF9S1erU",
  },
  {
    urls: "turn:a.relay.metered.ca:443",
    username: "13f18f9bc955e70d76cc28e3",
    credential: "9PoAPBZesF9S1erU",
  },
  {
    urls: "turn:a.relay.metered.ca:443?transport=tcp",
    username: "13f18f9bc955e70d76cc28e3",
    credential: "9PoAPBZesF9S1erU",
  },
];
const deviceConnection = new RTCPeerConnection({
  bundlePolicy: "max-compat",
  iceServers: ICE_SERVERS,
  iceCandidatePoolSize: 0,
  iceTransportPolicy: "all",
});
deviceConnection.createDataChannel("terminal");

async function publishOffer() {
  const offer = await deviceConnection.createOffer({
    offerToReceiveAudio: true,
    offerToReceiveVideo: true,
  });
  await deviceConnection.setLocalDescription(offer);
  console.log(deviceConnection.localDescription);
}

export const a = "a";
