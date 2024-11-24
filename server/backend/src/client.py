import msgspec
from httpx import AsyncClient

from models import WebrtcOffer


class SwarmNodeClient:

    def __init__(self, root_url: str, additional_headers: dict[str,str]):
        self.root_url=root_url.removesuffix("/")
        self.a_headers=additional_headers
        self.encoder=msgspec.json.Encoder()
        self.offer_decoder=msgspec.json.Decoder(WebrtcOffer)

    async def webrtc_offer(self, webrtc_offer: WebrtcOffer) -> WebrtcOffer:
        async with AsyncClient() as cl:
            r=await cl.put(self.root_url+"/webrtc", json=self.encoder.encode(webrtc_offer))
        return self.offer_decoder.decode(r.raise_for_status().json())

    async def get_kernel_id(self)->str:
        async with AsyncClient() as cl:
            r=await cl.get(self.root_url+"/k")
            r=r.raise_for_status().json()
        return msgspec.json.decode(r,type=str)
