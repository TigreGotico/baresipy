"""Registrar-capable inbound voice-assistant example.

Answers incoming SIP calls, listens to the caller via an OVOS
`ovos-simple-listener`, transcribes speech and echoes it back with TTS.

Required installs:
    pip install baresipy[ovos] ovos-stt-plugin-server ovos-vad-plugin-webrtcvad

Plugin selection (which STT/VAD/TTS engine actually runs) is read by the
OVOS Plugin Manager factories (`OVOSSTTFactory`, `OVOSVADFactory`, and
`baresipy`'s own TTS lookup) from `mycroft.conf`, so this example stays
generic - swap plugins by editing your `mycroft.conf`, not this script.
"""
from time import sleep

from ovos_plugin_manager.stt import OVOSSTTFactory
from ovos_plugin_manager.vad import OVOSVADFactory
from ovos_simple_listener import ListenerCallbacks, SimpleListener

from baresipy import BareSIP
from baresipy.ovos import BareSIPMicrophone
from baresipy.utils.log import LOG

gateway = "your_sip.gateway.net"
user = "your_phone"
pswd = "your_password"


class VoiceBotCallbacks(ListenerCallbacks):
    sip: "VoiceBot" = None

    @classmethod
    def text_callback(cls, utterance: str, lang: str):
        LOG.info(f"STT: {utterance}")
        if cls.sip is not None:
            cls.sip.speak(f"you said: {utterance}")


class VoiceBot(BareSIP):
    def __init__(self, *args, **kwargs):
        kwargs["record_rx"] = True
        super().__init__(*args, **kwargs)
        self.listener = None
        VoiceBotCallbacks.sip = self

    def handle_incoming_call(self, number: str) -> None:
        LOG.info("Incoming call: " + number)
        self.accept_call()

    def handle_call_established(self) -> None:
        LOG.info("Call established, starting listener")
        mic = BareSIPMicrophone(sip=self)
        self.listener = SimpleListener(
            mic=mic,
            wakeword=None,
            vad=OVOSVADFactory.create(),
            stt=OVOSSTTFactory.create(),
            callbacks=VoiceBotCallbacks(),
        )
        self.listener.start()

    def handle_call_ended(self, reason: str, number=None) -> None:
        LOG.info("Call ended")
        if self.listener is not None:
            self.listener.stop()
            self.listener = None


if __name__ == "__main__":
    bot = VoiceBot(user, pswd, gateway, debug=False)
    while bot.running:
        sleep(0.5)
