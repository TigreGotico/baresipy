"""E2E caller: a registrar-less, headless baresip instance that dials the
`callee` service directly by SIP URI (no registrar involved), sends DTMF "7"
and a generated sine-wave wav once established, waits for the callee's
DTMF "42" echo, keeps the call up for several lengths of the idle silence
file, then hangs up and writes a JSON results summary that
test/e2e/test_call.py asserts on.

What the caller receives must be silence: the callee sends no audio, so any
sound on the caller's rx leg is its own tone coming back (an echo).

Run inside the `caller` service of docker-compose.e2e.yml.
"""
import os
import sys
import time
from os.path import getsize, join

from pydub.generators import Sine

from _common import SHARED, SOUND_RMS, IDLE_SILENCE_SECONDS, E2EBareSIP, \
    write_status, write_json, headless_config_with_sip_listen, \
    codec_modules_enabled, pcm16_rms

CONFIG_PATH = "/root/.baresipy_caller"
CALLEE_URI = os.environ.get("CALLEE_URI", "sip:callee@172.31.99.10:5060")

# long enough that both sides must re-arm the idle silence at least twice
HOLD_SECONDS = 3 * IDLE_SILENCE_SECONDS + 2


class Caller(E2EBareSIP):
    def __init__(self, *args, **kwargs):
        self.dtmf_received = []
        self.established = False
        super().__init__(*args, **kwargs)

    def handle_ready(self) -> None:
        write_status("caller", "ready")

    def handle_call_established(self) -> None:
        self.established = True
        write_status("caller", "established")

    def handle_dtmf_received(self, char: str, duration: int) -> None:
        self.dtmf_received.append(char)
        write_status("caller", "dtmf received '{0}'".format(char))

    def handle_call_ended(self, reason: str, number=None) -> None:
        write_status("caller", "call ended reason={0}".format(reason))


def make_sine_wav() -> str:
    path = join("/tmp", "e2e_sine.wav")
    tone = Sine(440).to_audio_segment(duration=4000)
    tone = tone.set_frame_rate(48000).set_channels(2)
    tone.export(path, format="wav")
    return path


def main() -> int:
    headless_config_with_sip_listen(CONFIG_PATH)
    write_status("caller", "starting")

    results = {
        "call_established": False,
        "established_at_end": False,
        "hold_seconds": HOLD_SECONDS,
        "caller_dtmf_received": [],
        "caller_idle_rearms": 0,
        "rx_wav": None,
        "rx_wav_size": 0,
        "rx_rms": None,
        "rx_has_sound": False,
        "caller_codec_modules": None,
    }

    bs = Caller(user="caller", headless=True, record_rx=True,
                recording_path=join(SHARED, "caller_rx"),
                config_path=CONFIG_PATH, autostart=True, block=True)

    try:
        # give the callee container a head start to boot baresip
        time.sleep(3)
        write_status("caller", "dialling " + CALLEE_URI)
        bs.call(CALLEE_URI)

        deadline = time.time() + 30
        while not bs.call_established and time.time() < deadline:
            time.sleep(0.2)

        if bs.call_established:
            bs.send_dtmf("7", mode="keys")
            write_status("caller", "sent dtmf 7")
            sine = make_sine_wav()
            bs.send_audio(sine)

        # keep the call up past several ends of the idle silence file; if
        # the idle source is not re-armed, baresip closes the call here
        time.sleep(HOLD_SECONDS)

        results["call_established"] = bool(bs.established)
        results["established_at_end"] = bool(bs.call_established)
        results["caller_dtmf_received"] = list(bs.dtmf_received)
        results["caller_idle_rearms"] = bs.idle_rearms
        results["caller_codec_modules"] = codec_modules_enabled(bs.config)

        bs.hang()

        rx_wav = bs.get_rx_wav(timeout=5)
        results["rx_wav"] = rx_wav
        if rx_wav:
            results["rx_wav_size"] = getsize(rx_wav)
            try:
                results["rx_rms"] = pcm16_rms(rx_wav)
                results["rx_has_sound"] = (results["rx_rms"] or 0) > SOUND_RMS
            except Exception as e:
                write_status("caller", "failed to analyze rx wav: " + str(e))
    finally:
        write_json("results.json", results)
        write_status("caller", "results written: " + str(results))
        # let the callee write callee_rx.json after the hangup
        time.sleep(8)
        bs.quit()

    return 0 if results["call_established"] else 1


if __name__ == "__main__":
    sys.exit(main())
