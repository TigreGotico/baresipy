"""Voicemail / answering-machine bot.

Auto-answers incoming calls, speaks a greeting, records the caller (via
`record_rx=True` + `get_rx_wav()`), caps the message at 60 seconds, then says
goodbye and hangs up. When the call ends, the finished rx wav is copied into
`./voicemail/<timestamp>-<caller_user>.wav`.

If an OVOS STT plugin is configured in `mycroft.conf`, the recording is also
transcribed to a sibling `.txt` file - this is best-effort and skipped
gracefully if `ovos-plugin-manager`/`[ovos]` isn't installed or no STT plugin
is configured.

Required installs:
    pip install baresipy[ovos]
"""
import threading
from datetime import datetime
from os import makedirs
from os.path import isdir, join
from shutil import copyfile
from time import sleep

from baresipy import BareSIP
from baresipy.utils.log import LOG

gateway = "your_sip.gateway.net"
user = "your_phone"
pswd = "your_password"

VOICEMAIL_DIR = "./voicemail"
MAX_MESSAGE_SECONDS = 60


def transcribe(wav_path: str) -> str:
    """Best-effort transcription using whatever STT plugin `mycroft.conf`
    configures. Returns "" if no plugin is available."""
    try:
        from ovos_plugin_manager.stt import OVOSSTTFactory
    except ImportError:
        LOG.info("ovos-plugin-manager not installed, skipping transcription")
        return ""
    try:
        stt = OVOSSTTFactory.create()
        with open(wav_path, "rb") as f:
            audio_data = f.read()
        return stt.execute(audio_data) or ""
    except Exception as e:
        LOG.warning(f"transcription skipped: {e}")
        return ""


class VoicemailBot(BareSIP):
    def __init__(self, *args, **kwargs):
        kwargs["record_rx"] = True
        super().__init__(*args, **kwargs)
        self._cutoff_timer = None
        if not isdir(VOICEMAIL_DIR):
            makedirs(VOICEMAIL_DIR)

    def handle_incoming_call(self, number: str) -> None:
        LOG.info("Incoming call: " + number)
        self.accept_call()

    def handle_call_established(self) -> None:
        self.speak("Nobody is available to take your call. "
                    "Please leave a message after the tone.")
        self._cutoff_timer = threading.Timer(
            MAX_MESSAGE_SECONDS, self._cutoff_message)
        self._cutoff_timer.daemon = True
        self._cutoff_timer.start()

    def _cutoff_message(self) -> None:
        if not self.call_established:
            return
        self.speak("Message length limit reached. Goodbye.")
        self.hang()

    def handle_call_ended(self, reason: str, number=None) -> None:
        LOG.info("Call ended, saving voicemail")
        if self._cutoff_timer is not None:
            self._cutoff_timer.cancel()
            self._cutoff_timer = None

        info = self.call_history[-1] if self.call_history else None
        caller_user = (info.user if info and info.user else "unknown")
        wav_path = self.get_rx_wav(timeout=5.0)
        if not wav_path:
            LOG.warning("no voicemail recording found")
            return

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = join(VOICEMAIL_DIR, f"{timestamp}-{caller_user}.wav")
        copyfile(wav_path, dest)
        LOG.info("saved voicemail to " + dest)

        transcript = transcribe(dest)
        if transcript:
            with open(dest[:-4] + ".txt", "w") as f:
                f.write(transcript)
            LOG.info("transcript: " + transcript)


if __name__ == "__main__":
    bot = VoicemailBot(user, pswd, gateway, headless=True)
    while bot.running:
        sleep(0.5)
