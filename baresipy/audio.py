"""Helpers for tailing baresip `sndfile` module wav recordings and doing
lightweight pure-stdlib PCM resampling (no `audioop` - removed in Python
3.13 - and no numpy dependency).
"""
import struct
import time
from os.path import isfile
from typing import Optional


class WavTailReader:
    """Incrementally read a wav file that is still being written to.

    baresip's `sndfile` module writes the RIFF/fmt header first (so
    channels/rate/bits-per-sample can be read as soon as the header bytes
    exist), but the RIFF/data chunk SIZE fields are only finalized when the
    file is closed. This reader parses the fmt chunk once, then keeps
    reading raw PCM bytes appended after the data-chunk header, ignoring the
    (stale, likely zero) size field, and tolerates the file not existing
    yet.
    """

    def __init__(self, path: str, timeout: float = 5.0):
        self.path = path
        self.sample_rate: int = 0
        self.sample_width: int = 0
        self.channels: int = 0
        self._data_offset: int = 0
        self._pos: int = 0
        self._closed = False
        self._wait_for_header(timeout)

    def _wait_for_header(self, timeout: float) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if isfile(self.path):
                try:
                    with open(self.path, "rb") as f:
                        header = f.read(4096)
                    if self._parse_header(header):
                        return
                except OSError:
                    pass
            time.sleep(0.05)
        raise TimeoutError(
            f"wav header for {self.path!r} not available after "
            f"{timeout}s")

    def _parse_header(self, header: bytes) -> bool:
        if len(header) < 12 or header[0:4] != b"RIFF" or \
                header[8:12] != b"WAVE":
            return False
        offset = 12
        fmt_found = False
        while offset + 8 <= len(header):
            chunk_id = header[offset:offset + 4]
            chunk_size = struct.unpack_from("<I", header, offset + 4)[0]
            chunk_body_start = offset + 8
            if chunk_id == b"fmt ":
                if chunk_body_start + 16 > len(header):
                    return False
                (_audio_format, channels, sample_rate, _byte_rate,
                 _block_align, bits_per_sample) = struct.unpack_from(
                    "<HHIIHH", header, chunk_body_start)
                self.channels = channels
                self.sample_rate = sample_rate
                self.sample_width = bits_per_sample // 8
                fmt_found = True
            elif chunk_id == b"data":
                if not fmt_found:
                    return False
                self._data_offset = chunk_body_start
                return True
            offset = chunk_body_start + chunk_size + (chunk_size % 2)
        return False

    def read(self, n_bytes: int, timeout: Optional[float] = None) -> bytes:
        """Block (polling) up to `timeout` seconds for `n_bytes` of new raw
        PCM data past the data-chunk header. Returns whatever is available
        (possibly `b""`) if the timeout elapses or the file is gone/closed.
        """
        if self._closed:
            return b""
        timeout = 5.0 if timeout is None else timeout
        deadline = time.time() + timeout
        buf = b""
        while len(buf) < n_bytes and time.time() < deadline:
            if not isfile(self.path):
                break
            try:
                with open(self.path, "rb") as f:
                    f.seek(self._data_offset + self._pos)
                    chunk = f.read(n_bytes - len(buf))
            except OSError:
                break
            if chunk:
                buf += chunk
                self._pos += len(chunk)
            else:
                time.sleep(0.01)
        return buf

    def close(self) -> None:
        self._closed = True


def resample_pcm16(data: bytes, src_rate: int, src_channels: int,
                    dst_rate: int = 16000) -> bytes:
    """Downmix multi-channel 16-bit signed PCM (little-endian) to mono by
    averaging channels, then linearly resample from `src_rate` to
    `dst_rate`. Pure stdlib, no audioop/numpy.
    """
    if not data:
        return b""

    src_channels = max(1, src_channels)
    frame_size = 2 * src_channels
    n_frames = len(data) // frame_size
    if n_frames == 0:
        return b""

    samples = struct.unpack_from("<%dh" % (n_frames * src_channels), data)

    if src_channels > 1:
        mono = [
            sum(samples[i * src_channels:(i + 1) * src_channels]) //
            src_channels
            for i in range(n_frames)
        ]
    else:
        mono = list(samples)

    if src_rate == dst_rate:
        out = mono
    else:
        ratio = src_rate / float(dst_rate)
        out_len = int(n_frames / ratio)
        out = []
        for i in range(out_len):
            src_pos = i * ratio
            idx = int(src_pos)
            frac = src_pos - idx
            s0 = mono[idx] if idx < n_frames else mono[-1]
            idx1 = idx + 1
            s1 = mono[idx1] if idx1 < n_frames else mono[-1]
            val = s0 + (s1 - s0) * frac
            out.append(int(val))

    # clamp to int16 range
    out = [max(-32768, min(32767, v)) for v in out]
    return struct.pack("<%dh" % len(out), *out)
