import asyncio
import dataclasses
import logging
import threading
from contextlib import asynccontextmanager
from fractions import Fraction
from typing import Any, AsyncGenerator

import gi
import numpy as np

gi.require_version("Gst", "1.0")
gi.require_version("GstApp", "1.0")
gi.require_version("GstVideo", "1.0")
from gi.repository import Gst, GstApp, GstVideo, GObject

Gst.init()

glib_thread = None


def init_gobject():
    global glib_thread
    if glib_thread is not None:
        return
    GObject.threads_init()
    glib_thread = threading.Thread(target=GObject.MainLoop().run, daemon=True).start()


@dataclasses.dataclass(slots=True)
class GstVideoSource:
    queue: asyncio.Queue[np.ndarray] = dataclasses.field(default_factory=asyncio.Queue)
    counter: int = 0
    height: int = 0
    width: int = 0
    channels: int = 0
    fps: Fraction = Fraction(0, 1)
    video_frmt: GstVideo.VideoFormat = GstVideo.VideoFormat.UNKNOWN
    initialized: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)


def gst_buffer_to_numpy(
    buffer: Gst.Buffer, height: int, width: int, fmt: GstVideo.VideoFormat
) -> np.ndarray:
    success, map_info = buffer.map(Gst.MapFlags.READ)
    if not success:
        raise RuntimeError("Failed to map Gst.Buffer")

    try:
        # Extract the raw data
        data = map_info.data
        if fmt == GstVideo.VideoFormat.RGB or fmt == GstVideo.VideoFormat.BGR:
            # RGB has 3 channels
            array = np.frombuffer(data, dtype=np.uint8).reshape((height, width, 3))
        elif fmt == GstVideo.VideoFormat.GRAY8:
            # Grayscale has 1 channel
            array = np.frombuffer(data, dtype=np.uint8).reshape((height, width))
        elif fmt == GstVideo.VideoFormat.I420:
            # I420 is a planar YUV format: Y plane, U plane, V plane
            array = np.frombuffer(data, dtype=np.uint8).reshape(
                (height + height // 2, width)
            )
        else:
            raise ValueError(f"Unsupported format: {format}")
        return array
    finally:
        # Unmap the buffer to release its memory
        buffer.unmap(map_info)


async def _on_buffer(sink: GstApp.AppSink, vs: GstVideoSource) -> Gst.FlowReturn:
    """Callback on 'new-sample' signal"""
    # Emit 'pull-sample' signal
    # https://lazka.github.io/pgi-docs/GstApp-1.0/classes/AppSink.html#GstApp.AppSink.signals.pull_sample

    sample: Gst.Sample = sink.pull_sample()
    if not isinstance(sample, Gst.Sample):
        logging.error(
            "Error : Not expected buffer type: %s != %s", type(sample), Gst.Sample
        )
        return Gst.FlowReturn.ERROR

    vs.counter += 1
    if not vs.initialized.is_set():
        caps: Gst.Caps = sample.get_caps()
        structure: Gst.Structure = caps.get_structure(0)
        val_set, vs.height = structure.get_int("height")
        assert val_set, "height not set"
        val_set, vs.width = structure.get_int("width")
        assert val_set, "width not set"
        val_set, num, denom = structure.get_fraction("framerate")
        assert val_set, "framerate not set"
        vs.fps = Fraction(num, denom)
        frmt_str = structure.get_string("format")
        assert frmt_str is not None, "format not set"
        vs.video_frmt = GstVideo.VideoFormat.from_string(frmt_str)
        format_info: GstVideo.VideoFormatInfo = GstVideo.VideoFormat.get_info(
            vs.video_frmt
        )
        vs.channels = format_info.n_components
        assert val_set, "format not set"
        vs.initialized.set()
    buffer: Gst.Buffer = sample.get_buffer()
    frame = gst_buffer_to_numpy(buffer, vs.height, vs.width, vs.video_frmt)
    await vs.queue.put(frame)
    return Gst.FlowReturn.OK


def on_buffer(
    sink: GstApp.AppSink, vs: GstVideoSource, loop: asyncio.AbstractEventLoop
) -> Gst.FlowReturn:
    """Callback on 'new-sample' signal"""
    try:
        return asyncio.run_coroutine_threadsafe(_on_buffer(sink, vs), loop).result()
    except Exception as e:
        logging.exception(e)
        return Gst.FlowReturn.ERROR


@asynccontextmanager
async def gst_video_source(pipeline: list[str]) -> AsyncGenerator[GstVideoSource, Any]:
    app_sink_str = "appsink emit-signals=True drop=true sync=false name=appsink"
    pipeline_str = " ! ".join(pipeline + [app_sink_str])
    pipeline: Gst.Pipeline = Gst.parse_launch(pipeline_str)
    app_sink: GstApp.AppSink = pipeline.get_by_name("appsink")
    assert app_sink is not None, "appsink not found in pipeline"
    source = GstVideoSource()
    app_sink.connect("new-sample", on_buffer, source, asyncio.get_event_loop())
    pipeline.set_state(Gst.State.PLAYING)
    bus: Gst.Bus = pipeline.get_bus()
    bus.add_signal_watch()

    def bus_func(_: Gst.Bus, message: Gst.Message) -> bool:
        if message.type == Gst.MessageType.EOS:
            raise RuntimeError("EOS")
        elif message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            raise RuntimeError(f"Error: {err}, {debug}")
        return True

    bus.add_watch(Gst.MessageType.ERROR | Gst.MessageType.EOS, bus_func)
    await source.initialized.wait()
    try:
        yield source
    finally:
        pipeline.set_state(Gst.State.NULL)
