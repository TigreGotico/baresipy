"""Small helpers shared by the callee/caller e2e scripts.

Both scripts run inside their own container (see ../../docker-compose.e2e.yml)
and talk to each other purely over SIP/RTP - the only side-channel is a
bind-mounted /shared volume, used for status breadcrumbs and the results
json files the two scripts write.
"""
import json
import struct
import time
from os import makedirs
from os.path import join, isdir
from typing import Optional

from baresipy import BareSIP
from baresipy.config import render_config, ensure_silence_wav

SHARED = "/shared"

# The e2e instances use a short silence file, so a call of a few dozen
# seconds has to re-arm the headless idle source several times. With a
# 60 s file (the default) the call would end long before the file does.
IDLE_SILENCE_SECONDS = 8
IDLE_REARM_MARGIN = 2.0

# rms above this is sound; a decoded G.711 silence leg is ~0
SOUND_RMS = 50


class E2EBareSIP(BareSIP):
    """BareSIP with the short e2e silence file and a re-arm counter."""
    idle_silence_seconds = IDLE_SILENCE_SECONDS
    idle_rearm_margin = IDLE_REARM_MARGIN

    def __init__(self, *args, **kwargs):
        self.idle_rearms = 0
        super().__init__(*args, **kwargs)

    def _rearm_idle_source(self, generation: int) -> None:
        if generation == self._idle_generation and self.call_established:
            self.idle_rearms += 1
        super()._rearm_idle_source(generation)


def codec_modules_enabled(config: str) -> dict:
    """Return which audio codec modules are active (uncommented) in a
    rendered baresip config, keyed by module name without the `.so`
    suffix, eg `{"opus": False, "g711": True}`.

    Read off the actual config text a BareSIP instance loaded (its
    `.config` attribute), not assumed, so a test can confirm which codec
    family a call was even able to negotiate.
    """
    lines = [line.strip() for line in config.splitlines()]
    return {
        name: ("module\t\t\t" + name + ".so") in lines
        for name in ("opus", "g711")
    }


def pcm16_rms(wav_path: str) -> Optional[int]:
    """RMS of the 16-bit PCM samples in a sndfile recording.

    sndfile only writes the wav header size fields when the file is
    closed, so this reads the raw PCM after the 44-byte header and does
    not trust those fields.
    """
    with open(wav_path, "rb") as f:
        raw = f.read()[44:]
    n = len(raw) // 2
    if n == 0:
        return None
    samples = struct.unpack("<%dh" % n, raw[:n * 2])
    return int((sum(s * s for s in samples) / n) ** 0.5)


def write_status(name: str, msg: str) -> None:
    if not isdir(SHARED):
        makedirs(SHARED, exist_ok=True)
    line = "{ts:.3f} [{name}] {msg}\n".format(ts=time.time(), name=name,
                                               msg=msg)
    print(line, end="")
    with open(join(SHARED, name + "_status.log"), "a") as f:
        f.write(line)


def write_json(filename: str, data: dict) -> None:
    if not isdir(SHARED):
        makedirs(SHARED, exist_ok=True)
    with open(join(SHARED, filename), "w") as f:
        json.dump(data, f, indent=2)


def headless_config_with_sip_listen(config_path: str,
                                     bind: str = "0.0.0.0:5060") -> None:
    """Write a headless baresip config to `config_path/config`, patching
    `sip_listen` so the SIP UA binds an address reachable from other
    containers on the compose network (baresip's default listen address
    is not guaranteed to be the container's routable interface).

    The headless source points at `config_path/silence.wav`, the same file
    E2EBareSIP re-arms, IDLE_SILENCE_SECONDS long.

    Test-only, not part of what render_config() ships to users: also
    disables opus.so so the two e2e instances can only negotiate G.711
    (PCMU/PCMA) - the 8kHz case issue #60 is about. Use
    codec_modules_enabled() on the returned config text to confirm this.
    """
    if not isdir(config_path):
        makedirs(config_path, exist_ok=True)
    silence = ensure_silence_wav(config_path, seconds=IDLE_SILENCE_SECONDS)
    cfg = render_config(headless=True, silence_wav=silence)
    cfg = cfg.replace("#sip_listen\t\t0.0.0.0:5060",
                       "sip_listen\t\t" + bind)
    cfg = cfg.replace("module\t\t\topus.so", "#module\t\t\topus.so")
    with open(join(config_path, "config"), "w") as f:
        f.write(cfg)
