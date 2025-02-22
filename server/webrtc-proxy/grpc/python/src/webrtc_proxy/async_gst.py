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
from gi.repository import Gst, GstApp, GstVideo, GObject, GLib

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
    _queue: asyncio.Queue[np.ndarray] = dataclasses.field(default_factory=asyncio.Queue)
    counter: int = 0
    height: int = 0
    width: int = 0
    fps: Fraction = Fraction(0, 1)
    video_frmt: GstVideo.VideoFormat = GstVideo.VideoFormat.UNKNOWN
    initialized: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
    _error: Exception | None = None

    def set_error(self, error: Exception):
        self._error = error

    async def get(self):
        if self._error is not None:
            raise self._error
        return await self._queue.get()


class UnsupportedFormatError(Exception):
    """Raised when an unsupported video format is encountered."""

    pass


def gst_buffer_to_numpy(
    buffer: Gst.Buffer, height: int, width: int, fmt: GstVideo.VideoFormat
) -> np.ndarray:
    """Converts a Gst.Buffer to a numpy array.
    :raise: UnsupportedFormatError if the format is unsupported.
    :raise: RuntimeError if the buffer cannot be mapped.
    """
    success, map_info = buffer.map(Gst.MapFlags.READ)
    if not success:
        raise RuntimeError("Failed to map Gst.Buffer")
    try:
        # Extract the raw data
        data = map_info.data
        if fmt in [
            GstVideo.VideoFormat.RGB,
            GstVideo.VideoFormat.BGR,
            GstVideo.VideoFormat.GBR,
        ]:
            # RGB has 3 channels
            array = np.frombuffer(data, dtype=np.uint8).reshape((height, width, 3))
        elif fmt == GstVideo.VideoFormat.GRAY8:
            # Grayscale has 1 channel
            array = np.frombuffer(data, dtype=np.uint8).reshape((height, width))
        elif fmt in [
            GstVideo.VideoFormat.I420,
            GstVideo.VideoFormat.NV12,
            GstVideo.VideoFormat.YV12,
            GstVideo.VideoFormat.NV21,
        ]:
            array = np.frombuffer(data, dtype=np.uint8).reshape((height + height // 2, width))
        else:
            raise UnsupportedFormatError(f"Unsupported format: {fmt}")
        return array
    finally:
        # Unmap the buffer to release its memory
        buffer.unmap(map_info)


def on_buffer(
    sink: GstApp.AppSink, vs: GstVideoSource, loop: asyncio.AbstractEventLoop
) -> Gst.FlowReturn:
    try:
        sample: Gst.Sample = sink.pull_sample()
        if not isinstance(sample, Gst.Sample):
            logging.error("Error : Not expected buffer type: %s != %s", type(sample), Gst.Sample)
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
            assert val_set, "format not set"
            vs.initialized.set()
        buffer: Gst.Buffer = sample.get_buffer()
        frame = gst_buffer_to_numpy(buffer, vs.height, vs.width, vs.video_frmt)
        asyncio.run_coroutine_threadsafe(vs._queue.put(frame), loop)
        return Gst.FlowReturn.OK
    except Exception as e:
        logging.exception(e)
        return Gst.FlowReturn.ERROR


@asynccontextmanager
async def gst_video_source(pipeline: list[str]) -> AsyncGenerator[GstVideoSource, Any]:
    app_sink_str = "appsink emit-signals=True drop=True sync=False name=appsink"
    pipeline_str = " ! ".join(pipeline + [app_sink_str])
    pipeline: Gst.Pipeline = Gst.parse_launch(pipeline_str)
    app_sink: GstApp.AppSink = pipeline.get_by_name("appsink")
    assert app_sink is not None, "appsink not found in pipeline"
    source = GstVideoSource()
    app_sink.connect("new-sample", on_buffer, source, asyncio.get_event_loop())
    bus: Gst.Bus = pipeline.get_bus()
    loop = asyncio.get_event_loop()

    def bus_func(_: Gst.Bus, message: Gst.Message) -> bool:
        if message.type == Gst.MessageType.EOS:
            loop.call_soon_threadsafe(source.initialized.set)
            loop.call_soon_threadsafe(source.set_error, RuntimeError("EOS"))
            return False
        elif message.type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            loop.call_soon_threadsafe(source.initialized.set)
            loop.call_soon_threadsafe(source.set_error, RuntimeError(f"GST: {err}, {debug}"))
            return False
        return True

    bus.add_watch(GLib.PRIORITY_DEFAULT, bus_func)
    pipeline.set_state(Gst.State.PLAYING)
    await asyncio.wait_for(source.initialized.wait(), timeout=5)
    try:
        yield source
    finally:
        bus.remove_watch()
        pipeline.set_state(Gst.State.NULL)
        app_sink.set_state(Gst.State.NULL)
        while pipeline.get_state(Gst.CLOCK_TIME_NONE)[0] != Gst.StateChangeReturn.SUCCESS:
            await asyncio.sleep(0.1)
        logging.debug("Pipeline set to NULL")


@dataclasses.dataclass(slots=True)
class GstVideoSink:
    height: int
    width: int
    video_frmt: GstVideo.VideoFormat
    fps: Fraction
    _queue: asyncio.Queue[np.ndarray] = dataclasses.field(default_factory=asyncio.Queue)

    offset: int = 0
    pts: int = 0
    duration: int = 0
    _error: Exception | None = None

    def set_error(self, error: Exception):
        self._error = error

    def __post_init__(self):
        self.duration = int(10**9 / (self.fps.numerator / self.fps.denominator))

    async def put(self, frame: np.ndarray):
        if self._error is not None:
            raise self._error
        await self._queue.put(frame)

    async def stream_buffers(self, src: GstApp.AppSrc):
        while self._error is None:
            frame = await self._queue.get()
            gst_buffer: Gst.Buffer = Gst.Buffer.new_wrapped(frame.tobytes())
            gst_buffer.dts = Gst.CLOCK_TIME_NONE
            gst_buffer.duration = self.duration
            gst_buffer.pts = self.pts
            gst_buffer.offset = self.offset
            self.pts += self.duration
            self.offset += 1
            while True:
                result: Gst.FlowReturn = GstApp.AppSrc.push_buffer(src, gst_buffer)
                if result == Gst.FlowReturn.EOS:
                    raise RuntimeError("EOS")
                elif result == Gst.FlowReturn.FLUSHING:
                    await asyncio.sleep(0.1)
                elif result == Gst.FlowReturn.OK:
                    break
        raise self._error


@asynccontextmanager
async def gst_video_sink(
    pipeline: list[str],
    width: int,
    height: int,
    fps: Fraction,
    video_frmt: GstVideo.VideoFormat,
) -> AsyncGenerator[GstVideoSink, Any]:
    sink = GstVideoSink(height=height, width=width, fps=fps, video_frmt=video_frmt)
    app_src_str = f"appsrc emit-signals=False is-live=True leaky-type=upstream name=appsrc format=time max-time={5 * sink.duration}"
    cap_str = f"video/x-raw,format={GstVideo.VideoFormat.to_string(video_frmt)},width={width},height={height},framerate={fps.numerator}/{fps.denominator}"
    pipeline_str = " ! ".join([app_src_str, cap_str] + pipeline)
    stream_task = None
    gst_pipeline: Gst.Pipeline | None = None
    try:
        gst_pipeline = Gst.parse_launch(pipeline_str)
        app_src: GstApp.AppSrc = gst_pipeline.get_by_name("appsrc")
        assert app_src is not None, "appsrc not found in pipeline"
        bus: Gst.Bus = gst_pipeline.get_bus()
        loop = asyncio.get_event_loop()

        def bus_func(_: Gst.Bus, message: Gst.Message) -> bool:
            if message.type == Gst.MessageType.EOS:
                loop.call_soon_threadsafe(sink.set_error, RuntimeError("EOS"))
                return False
            elif message.type == Gst.MessageType.ERROR:
                err, debug = message.parse_error()
                loop.call_soon_threadsafe(sink.set_error, RuntimeError(f"GST: {err}, {debug}"))
                return False
            return True

        bus.add_watch(GLib.PRIORITY_DEFAULT, bus_func)
        gst_pipeline.set_state(Gst.State.PLAYING)
        stream_task = asyncio.create_task(sink.stream_buffers(app_src))
        yield sink
    finally:
        if stream_task is not None and not stream_task.done():
            stream_task.cancel()
            try:
                await stream_task
            except asyncio.CancelledError:
                pass
        if gst_pipeline is not None:
            gst_pipeline.set_state(Gst.State.NULL)
