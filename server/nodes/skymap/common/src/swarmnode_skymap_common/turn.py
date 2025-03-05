import os

import httpx

from webrtc_proxy import pb


async def cloudflare_turn() -> pb.WebrtcConfig.IceServer:
    cf_turn_id = os.environ.get("CF_TURN_TOKEN_ID")
    assert cf_turn_id, "CF_TURN_TOKEN_ID not set"
    cf_turn_token = os.environ.get("CF_TURN_TOKEN")
    assert cf_turn_token, "CF_TURN_TOKEN not set"
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://rtc.live.cloudflare.com/v1/turn/keys/{cf_turn_id}/credentials/generate",
            headers={
                f"Authorization": f"Bearer {cf_turn_token}",
                "Content-Type": "application/json",
            },
            json={"ttl": 86400},  # 24 hours
        )
    response.raise_for_status()
    ice_servers: dict = response.json()["iceServers"]

    return pb.WebrtcConfig.IceServer(
        urls=ice_servers["urls"],
        username=ice_servers["username"],
        credential=ice_servers["credential"],
    )
