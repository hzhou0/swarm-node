import asyncio
import logging
import multiprocessing
import time
from datetime import datetime
from multiprocessing import connection
from multiprocessing.shared_memory import SharedMemory
from multiprocessing.synchronize import Lock

import av
import uvloop
from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCDataChannel,
    RTCConfiguration,
    RTCIceServer, MediaStreamTrack, VideoStreamTrack,
)
from aiortc.contrib.media import MediaRecorderContext
from av.video.frame import VideoFrame
from numpy import ndarray

from ipc import write_state, Daemon
from kernels.skymap.common import rgbd_stream_framerate
from kernels.skymap.server import reconstructor_d
from models import (
    WebrtcOffer,
    KernelState,
)
from util import configure_root_logger, ice_servers, root_dir, loop_forever

_pc: RTCPeerConnection = RTCPeerConnection()
_datachannel: RTCDataChannel | None = None
_sensor_video: VideoStreamTrack | None = None

_state = KernelState()
_state_mem: SharedMemory | None = None
_state_lock: Lock | None = None


def _commit_state():
    global _state_mem, _state_lock, _state
    _state_mem = write_state(_state_mem, _state_lock, _state)


@loop_forever(2.0)
async def keep_alive():
    if _datachannel is not None:
        _datachannel.send("")


async def on_connectionstatechange(pc: RTCPeerConnection):
    logging.info(f"Connection state is {pc.connectionState}")
    if pc.connectionState == "failed" or pc.connectionState == "closed":
        await pc.close()
        global _datachannel, _sensor_video
        _datachannel = None
        _sensor_video = None


def on_datachannel(channel: RTCDataChannel):
    def on_message(message: str):
        logging.info(f"Received message {message}")
        try:
            logging.info(
                f"Latency: {int(time.time() - float(message.split(';')[-1])) * 1000}ms"
            )
        except:
            pass

    channel.on("message", on_message)
    global _datachannel
    _datachannel = channel


class VideoSink:
    """
    A media sink that writes audio and/or video to a file.

    Examples:

    . code-block:: python

        # Write to a video file.
        player = MediaRecorder('/path/to/file.mp4')

        # Write to a set of images.
        player = MediaRecorder('/path/to/file-%3d.png')

    :param file: The path to a file, or a file-like object.
    :param format: The format to use, defaults to autodect.
    :param options: Additional options to pass to FFmpeg.
    """

    def __init__(self, file, track, format=None, options=None):
        self.__container = av.open(file=file, format=format, mode="w", options=options)
        self.track = track
        if self.__container.format.name == "image2":
            stream = self.__container.add_stream("png", rate=rgbd_stream_framerate)
            stream.pix_fmt = "rgb24"
        else:
            stream = self.__container.add_stream("libx264", rate=rgbd_stream_framerate)
            stream.pix_fmt = "yuv420p"
        self.context = MediaRecorderContext(stream)

    def stop(self):
        if self.__container:
            self.__container.close()
            self.__container = None

    async def add_frame(self, frame: VideoFrame):
        if not self.context.started:
            # adjust the output size to match the first frame
            if isinstance(frame, VideoFrame):
                self.context.stream.width = frame.width
                self.context.stream.height = frame.height
            self.context.started = True

        for packet in self.context.stream.encode(frame):
            self.__container.mux(packet)


_playback_sink: VideoSink | None = None


def on_track(track: MediaStreamTrack):
    if track.kind != 'video':
        logging.info(f"Ignoring track, kind is {track.kind}")
        return
    logging.info(f"Using video track {track}")
    global _sensor_video, _playback_sink
    _sensor_video = track
    if _playback_sink is not None:
        _playback_sink.stop()
    video_path=root_dir.joinpath(datetime.now().strftime("%Y.%m.%d-%H.%M.%S") + ".mp4")
    _playback_sink = VideoSink(video_path, track)
    logging.info(f"Recording received video to {video_path}")


async def handle_offer(offer: WebrtcOffer):
    import aioice.stun

    # aioice attempts stun lookup on private network ports: these queries will never resolve
    # These attempts will timeout after 5 seconds, making connection take 5+ seconds
    # Modifying retry globals here to make it fail faster and retry more aggressively
    # Retries follow an exponential fallback: 1,2,4,8 * RETRY_RTO
    aioice.stun.RETRY_MAX = 2
    aioice.stun.RETRY_RTO = 0.1
    pc = RTCPeerConnection(
        RTCConfiguration(
            [
                RTCIceServer(urls=s.urls, username=s.username, credential=s.credential)
                for s in ice_servers
            ]
        )
    )

    pc.add_listener("track", lambda track: on_track(track))
    pc.add_listener("connectionstatechange", lambda: on_connectionstatechange(pc))
    pc.add_listener("datachannel", lambda channel: on_datachannel(channel))

    logging.info(offer.sdp)
    await pc.setRemoteDescription(RTCSessionDescription(sdp=offer.sdp, type=offer.type))
    start = time.time()
    await pc.setLocalDescription(await pc.createAnswer())
    logging.info(f"ICE Candidates gathered in {time.time() - start}")
    logging.info(pc.localDescription.sdp)
    _state.webrtc_offer = WebrtcOffer(
        sdp=pc.localDescription.sdp, type=pc.localDescription.type, tracks=offer.tracks
    )
    _commit_state()

    global _pc
    await _pc.close()
    _pc = pc


@loop_forever(0.01)
async def process_frame(reconstruct_d: Daemon):
    global _sensor_video
    if _sensor_video is None:
        return
    try:
        frame: VideoFrame = await _sensor_video.recv()
        if _playback_sink is not None:
            await _playback_sink.add_frame(frame)
        try:
            reconstruct_d.mutate(frame.to_ndarray(format="bgr24"))
        except Exception as e:
            reconstruct_d.restart_if_failed()
            logging.exception(e)
    except Exception as e:
        logging.exception(e)
        _sensor_video = None


@loop_forever(0.01)
async def process_mutations(pipe: connection.Connection):
    while pipe.poll():
        mutation: WebrtcOffer = pipe.recv()
        match mutation:
            case WebrtcOffer():
                await handle_offer(mutation)


def main(
        state_mem: SharedMemory,
        state_lock: Lock,
        pipe: connection.Connection,
):
    multiprocessing.freeze_support()
    multiprocessing.spawn.freeze_support()
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    global _state_mem, _state_lock
    _state_mem, _state_lock = state_mem, state_lock
    _commit_state()
    configure_root_logger()
    av.logging.set_level(av.logging.PANIC)

    reconstruct_d: Daemon[None, ndarray, None] = Daemon(name="reconstructor", target=reconstructor_d.main)
    loop = asyncio.get_event_loop()
    # Specify tasks in a collection to avoid garbage collection
    _ = (
        loop.create_task(process_frame(reconstruct_d)),
        loop.create_task(process_mutations(pipe)),
        loop.create_task(keep_alive()),
    )
    try:
        loop.run_forever()
    finally:
        if _playback_sink is not None:
            _playback_sink.stop()
        for task in _:
            task.cancel()
        reconstruct_d.destroy()
