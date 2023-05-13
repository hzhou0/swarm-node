"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.a = void 0;
const ICE_SERVERS = [
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
exports.a = "a";
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoibWFpbi5qcyIsInNvdXJjZVJvb3QiOiIiLCJzb3VyY2VzIjpbIi4uL21haW4udHMiXSwibmFtZXMiOltdLCJtYXBwaW5ncyI6Ijs7O0FBQUEsTUFBTSxXQUFXLEdBQXdCO0lBQ3ZDO1FBQ0UsSUFBSSxFQUFFLDRCQUE0QjtLQUNuQztJQUNEO1FBQ0UsSUFBSSxFQUFFLDRCQUE0QjtRQUNsQyxRQUFRLEVBQUUsMEJBQTBCO1FBQ3BDLFVBQVUsRUFBRSxrQkFBa0I7S0FDL0I7SUFDRDtRQUNFLElBQUksRUFBRSwwQ0FBMEM7UUFDaEQsUUFBUSxFQUFFLDBCQUEwQjtRQUNwQyxVQUFVLEVBQUUsa0JBQWtCO0tBQy9CO0lBQ0Q7UUFDRSxJQUFJLEVBQUUsNkJBQTZCO1FBQ25DLFFBQVEsRUFBRSwwQkFBMEI7UUFDcEMsVUFBVSxFQUFFLGtCQUFrQjtLQUMvQjtJQUNEO1FBQ0UsSUFBSSxFQUFFLDJDQUEyQztRQUNqRCxRQUFRLEVBQUUsMEJBQTBCO1FBQ3BDLFVBQVUsRUFBRSxrQkFBa0I7S0FDL0I7Q0FDRixDQUFDO0FBQ0YsTUFBTSxnQkFBZ0IsR0FBRyxJQUFJLGlCQUFpQixDQUFDO0lBQzdDLFlBQVksRUFBRSxZQUFZO0lBQzFCLFVBQVUsRUFBRSxXQUFXO0lBQ3ZCLG9CQUFvQixFQUFFLENBQUM7SUFDdkIsa0JBQWtCLEVBQUUsS0FBSztDQUMxQixDQUFDLENBQUM7QUFDSCxnQkFBZ0IsQ0FBQyxpQkFBaUIsQ0FBQyxVQUFVLENBQUMsQ0FBQztBQUUvQyxLQUFLLFVBQVUsWUFBWTtJQUN6QixNQUFNLEtBQUssR0FBRyxNQUFNLGdCQUFnQixDQUFDLFdBQVcsQ0FBQztRQUMvQyxtQkFBbUIsRUFBRSxJQUFJO1FBQ3pCLG1CQUFtQixFQUFFLElBQUk7S0FDMUIsQ0FBQyxDQUFDO0lBQ0gsTUFBTSxnQkFBZ0IsQ0FBQyxtQkFBbUIsQ0FBQyxLQUFLLENBQUMsQ0FBQztJQUNsRCxPQUFPLENBQUMsR0FBRyxDQUFDLGdCQUFnQixDQUFDLGdCQUFnQixDQUFDLENBQUM7QUFDakQsQ0FBQztBQUVZLFFBQUEsQ0FBQyxHQUFHLEdBQUcsQ0FBQyJ9