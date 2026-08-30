"""E2E caller: a registrar-less, headless baresip instance that dials the
`callee` service directly by SIP URI (no registrar involved), sends DTMF "7"
and a generated sine-wave wav once established, waits for the callee's
DTMF "42" echo, then hangs up and writes a JSON results summary that
test/e2e/test_call.py asserts on.

Run inside the `caller` service of docker-compose.e2e.yml.
"""
import os
import sys
import time
from os.path import getsize, join

from pydub.generators import Sine

from _common import SHARED, write_status, write_json, \
    headless_config_with_sip_listen

from baresipy import BareSIP

CONFIG_PATH = "/root/.baresipy_caller"
CALLEE_URI = os.environ.get("CALLEE_URI", "sip:callee@172.31.99.10:5060")


class Caller(BareSIP):
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
        "caller_dtmf_received": [],
        "rx_wav": None,
        "rx_wav_size": 0,
        "rx_non_silent": False,
        "rx_rms": None,
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

        # let audio/DTMF flow both ways for a while
        time.sleep(10)

        results["call_established"] = bool(bs.established)
        results["caller_dtmf_received"] = list(bs.dtmf_received)

        rx_wav = bs.get_rx_wav(timeout=5)
        results["rx_wav"] = rx_wav
        if rx_wav:
            results["rx_wav_size"] = getsize(rx_wav)
            try:
                # sndfile only finalizes the wav header size fields when
                # the file is closed, so read the raw PCM past the header
                # instead of trusting them
                import struct
                with open(rx_wav, "rb") as f:
                    raw = f.read()[44:]
                n = len(raw) // 2
                samples = struct.unpack("<%dh" % n, raw[:n * 2])
                rms = int((sum(s * s for s in samples) / max(1, n)) ** 0.5)
                results["rx_rms"] = rms
                # a genuinely silent capture has rms ~0; a real
                # (encoded/decoded, possibly noisy) tone leg does not
                results["rx_non_silent"] = rms > 50
            except Exception as e:
                write_status("caller", "failed to analyze rx wav: " + str(e))

        bs.hang()
    finally:
        write_json("results.json", results)
        write_status("caller", "results written: " + str(results))
        bs.quit()

    return 0 if results["call_established"] else 1


if __name__ == "__main__":
    sys.exit(main())
