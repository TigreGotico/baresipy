"""E2E callee: a registrar-less, headless baresip instance that auto-accepts
incoming calls, records the received (rx) audio leg to /shared/callee_rx,
and 2s after the call is established sends back DTMF "42" so the caller can
assert bidirectional DTMF delivery.

The callee sends no audio of its own, so for the whole call its source is
the headless idle silence. When the call ends it writes callee_rx.json:
the rms of what it received (the caller's tone) and how many times it
re-armed the idle source.

Run inside the `callee` service of docker-compose.e2e.yml.
"""
import threading
import time
from os.path import getsize, join

from _common import SHARED, SOUND_RMS, E2EBareSIP, write_status, \
    write_json, headless_config_with_sip_listen, codec_modules_enabled, \
    pcm16_rms

CONFIG_PATH = "/root/.baresipy_callee"


class Callee(E2EBareSIP):
    def __init__(self, *args, **kwargs):
        self.dtmf_received = []
        super().__init__(*args, **kwargs)

    def handle_ready(self) -> None:
        write_status("callee", "ready")

    def handle_incoming_call(self, number: str) -> None:
        write_status("callee", "incoming call from " + number)
        self.accept_call()

    def handle_call_established(self) -> None:
        write_status("callee", "established")
        threading.Thread(target=self._send_dtmf_later, daemon=True).start()

    def _send_dtmf_later(self) -> None:
        time.sleep(2)
        if self.call_established:
            self.send_dtmf("42", mode="keys")
            write_status("callee", "sent dtmf 42")

    def handle_dtmf_received(self, char: str, duration: int) -> None:
        self.dtmf_received.append(char)
        write_status("callee", "dtmf received '{0}'".format(char))
        write_json("callee_dtmf.json", {"dtmf_received": self.dtmf_received})

    def handle_call_ended(self, reason: str, number=None) -> None:
        write_status("callee", "call ended reason={0}".format(reason))
        rx = {"rx_wav": None, "rx_wav_size": 0, "rx_rms": None,
              "rx_has_sound": False, "idle_rearms": self.idle_rearms,
              "end_reason": reason}
        try:
            rx_wav = self.get_rx_wav(timeout=5)
            rx["rx_wav"] = rx_wav
            if rx_wav:
                rx["rx_wav_size"] = getsize(rx_wav)
                rx["rx_rms"] = pcm16_rms(rx_wav)
                rx["rx_has_sound"] = (rx["rx_rms"] or 0) > SOUND_RMS
        except Exception as e:
            write_status("callee", "failed to analyze rx wav: " + str(e))
        write_json("callee_rx.json", rx)
        write_status("callee", "rx written: " + str(rx))


def main() -> None:
    headless_config_with_sip_listen(CONFIG_PATH)
    write_status("callee", "starting")

    bs = Callee(user="callee", headless=True, record_rx=True,
                recording_path=join(SHARED, "callee_rx"),
                config_path=CONFIG_PATH, autostart=True, block=True)
    write_status("callee", "spawned and ready for instructions")
    write_json("callee_codecs.json",
               {"callee_codec_modules": codec_modules_enabled(bs.config)})

    # stay up long enough for the caller container to dial in, exchange
    # audio/DTMF and hang up, then exit cleanly so `docker compose ... down`
    # (or an unexpectedly wedged run) doesn't hang forever.
    deadline = time.time() + 120
    try:
        while bs.running and time.time() < deadline:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        write_status("callee", "shutting down")
        bs.quit()


if __name__ == "__main__":
    main()
