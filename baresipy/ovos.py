"""OVOS integration - a `Microphone` plugin that streams SIP call audio
captured via baresip's `sndfile` module.

This module lazy-imports `ovos-plugin-manager` so that `import baresipy`
never requires it to be installed. Install it with `pip install
baresipy[ovos]`.
"""
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from baresipy.audio import WavTailReader, resample_pcm16
from baresipy.utils.log import LOG

try:
    from ovos_plugin_manager.templates.microphone import Microphone
except ImportError as e:
    raise ImportError(
        "ovos-plugin-manager is required for baresipy.ovos - "
        "install it with `pip install baresipy[ovos]`"
    ) from e

if TYPE_CHECKING:
    from baresipy import BareSIP


@dataclass
class BareSIPMicrophone(Microphone):
    """A `Microphone` plugin that reads audio the caller sent during an
    active SIP call, sourced from baresip's `sndfile`-recorded rx wav file.

    Requires the `BareSIP` instance to have been constructed with
    `record_rx=True`.
    """
    sip: Optional["BareSIP"] = None
    sample_rate: int = 16000
    sample_width: int = 2
    sample_channels: int = 1
    chunk_size: int = 4096

    _stream: Optional[WavTailReader] = field(default=None, repr=False)

    def start(self):
        if self.sip is None:
            raise ValueError("BareSIPMicrophone requires sip=<BareSIP instance>")
        while not self.sip.call_established:
            if self.sip.abort or not self.sip.running:
                return
            from time import sleep
            sleep(0.1)
        self._stream = self.sip.get_rx_stream()
        if self._stream is None:
            LOG.error("no rx recording available, is record_rx=True set?")

    def read_chunk(self) -> Optional[bytes]:
        if self._stream is None or self.sip is None or \
                not self.sip.call_established:
            return None

        dst_frame_bytes = self.sample_width * self.sample_channels
        needed_frames = self.chunk_size // dst_frame_bytes

        out = b""
        while len(out) < needed_frames * dst_frame_bytes:
            src_frame_size = self._stream.sample_width * \
                max(1, self._stream.channels)
            # read a generous amount of source bytes to produce enough
            # resampled output, accounting for the resample ratio
            ratio = self._stream.sample_rate / float(self.sample_rate) \
                if self.sample_rate else 1.0
            src_bytes_needed = int(
                (needed_frames - len(out) // dst_frame_bytes) *
                ratio) * src_frame_size
            src_bytes_needed = max(src_bytes_needed, src_frame_size)
            raw = self._stream.read(src_bytes_needed, timeout=1.0)
            if not raw:
                return None if not out else out
            resampled = resample_pcm16(
                raw, self._stream.sample_rate, self._stream.channels,
                dst_rate=self.sample_rate)
            out += resampled

        return out[:needed_frames * dst_frame_bytes]

    def stop(self):
        if self._stream is not None:
            self._stream.close()
            self._stream = None
