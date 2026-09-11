"""Barge-in voice agent - reference example for interactive agents.

Answers a call, reads the caller's rx audio stream (`get_rx_stream()`) on a
background thread, and runs a tiny stdlib energy-based VAD (RMS of
`resample_pcm16` chunks over a fixed threshold, no extra dependencies) to
detect when the caller is speaking. While the bot is talking, caller speech
above the threshold calls `stop_audio()` to interrupt playback immediately
(barge-in), which triggers `handle_audio_interrupted()`.

Collected caller audio between "started speaking" and "went quiet" is handed
to a pluggable `think(utterance)` function. This example doesn't ship any
STT - `think()` receives a placeholder utterance string; wire in real
transcription (eg. an OVOS STT plugin, as in `examples/voice_bot.py`) to
make it a real conversation.

Required installs:
    pip install baresipy[ovos]
"""
import threading
from time import sleep

from baresipy import BareSIP
from baresipy.audio import resample_pcm16
from baresipy.utils.log import LOG

gateway = "your_sip.gateway.net"
user = "your_phone"
pswd = "your_password"

VAD_RMS_THRESHOLD = 800
VAD_CHUNK_BYTES = 3200  # ~0.1s of 16kHz mono 16-bit PCM
SILENCE_CHUNKS_TO_END_TURN = 5


def rms(pcm16_mono: bytes) -> float:
    if not pcm16_mono:
        return 0.0
    import struct
    n = len(pcm16_mono) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack_from("<%dh" % n, pcm16_mono)
    return (sum(s * s for s in samples) / n) ** 0.5


def think(utterance: str) -> str:
    """Pluggable response generator. Default just echoes back."""
    return "you said: " + utterance


class ConversationalAgent(BareSIP):
    def __init__(self, *args, **kwargs):
        kwargs["record_rx"] = True
        super().__init__(*args, **kwargs)
        self._listen_thread = None
        self._stop_listening = threading.Event()

    def handle_incoming_call(self, number: str) -> None:
        LOG.info("Incoming call: " + number)
        self.accept_call()

    def handle_call_established(self) -> None:
        self._stop_listening.clear()
        self._listen_thread = threading.Thread(target=self._listen_loop,
                                                 daemon=True)
        self._listen_thread.start()
        self.speak("Hello, how can I help you today?")

    def handle_call_ended(self, reason: str, number=None) -> None:
        self._stop_listening.set()
        self._listen_thread = None

    def handle_audio_interrupted(self) -> None:
        LOG.info("Caller interrupted playback (barge-in)")

    def _listen_loop(self) -> None:
        stream = self.get_rx_stream()
        if stream is None:
            LOG.warning("no rx stream available, is record_rx working?")
            return

        speaking = False
        silence_run = 0
        utterance_chunks = []

        while not self._stop_listening.is_set() and self.call_established:
            raw = stream.read(VAD_CHUNK_BYTES, timeout=1.0)
            if not raw:
                continue
            mono = resample_pcm16(raw, stream.sample_rate, stream.channels,
                                   dst_rate=stream.sample_rate)
            level = rms(mono)
            caller_talking = level > VAD_RMS_THRESHOLD

            if caller_talking:
                if not speaking:
                    LOG.debug("caller started speaking")
                    speaking = True
                    utterance_chunks = []
                    self.stop_audio()  # barge-in: cut off any TTS playback
                silence_run = 0
                utterance_chunks.append(raw)
            elif speaking:
                silence_run += 1
                if silence_run >= SILENCE_CHUNKS_TO_END_TURN:
                    LOG.debug("caller went quiet, ending turn")
                    speaking = False
                    self._handle_utterance(utterance_chunks)
                    utterance_chunks = []

        stream.close()

    def _handle_utterance(self, chunks: list) -> None:
        # no bundled STT - this is a placeholder utterance, wire in a real
        # transcriber (eg. OVOSSTTFactory) to make this useful
        utterance = f"<{sum(len(c) for c in chunks)} bytes of caller audio>"
        response = think(utterance)
        self.speak(response, blocking=False)


if __name__ == "__main__":
    bot = ConversationalAgent(user, pswd, gateway, headless=True)
    while bot.running:
        sleep(0.5)
