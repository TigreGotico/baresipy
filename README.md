# baresipy

![](./logo.png)

A python wrapper around [baresip](https://github.com/baresip/baresip), the portable SIP user-agent.

Use it to place and receive VoIP calls from python. You can dial out, answer inbound calls, stream
text-to-speech or arbitrary audio into a call, send and receive DTMF, transcribe what a caller says,
and build interactive voice bots, with or without a SIP registrar, with or without a sound card.

## Install

```bash
sudo apt-get install baresip ffmpeg   # Debian/Ubuntu, see docs/setup.md for other distros
pip install baresipy
```

`baresip` is the SIP engine baresipy drives through `pexpect`. `ffmpeg` is used by `pydub` for audio
conversion. See [docs/setup.md](docs/setup.md) for per-distro install commands, SIP account
requirements, and troubleshooting.

Optional extras:

| extra | installs | needed for |
|---|---|---|
| `baresipy[ovos]` | `ovos-plugin-manager`, `phoonnx`, `ovos-simple-listener` | `speak()`/`say()` default TTS engine, `baresipy.ovos.BareSIPMicrophone`, voice bots |
| `baresipy[server]` | `fastapi`, `uvicorn`, `python-multipart` | `baresipy-gateway` HTTP/WebSocket API, see [docs/http-gateway.md](docs/http-gateway.md) |
| `baresipy[test]` | `pytest`, `pytest-cov`, `fastapi`, `httpx`, `python-multipart`, `uvicorn` | running the test suite |

## Quickstart

### Scripted call

Dial a number, speak, hang up:

```python
from baresipy import BareSIP
from time import sleep

b = BareSIP("your_user", "your_password", "your_sip_gateway.example")
b.call("someone@your_sip_gateway.example")

while b.running:
    sleep(0.5)
    if b.call_established:
        b.speak("hello, this is a test")
        b.hang()
        b.quit()
        break
```

Full runnable version: [examples/scripted_call.py](examples/scripted_call.py).

### Answering bot

Subclass `BareSIP` and override the event handlers:

```python
from baresipy import BareSIP
from time import sleep


class JokeBOT(BareSIP):
    def handle_incoming_call(self, number):
        self.accept_call()

    def handle_call_established(self):
        self.speak("Welcome to the jokes bot")
        self.speak("Goodbye")
        self.hang()


b = JokeBOT("your_user", "your_password", "your_sip_gateway.example")
while b.running:
    sleep(1)
```

Full runnable version: [examples/events.py](examples/events.py).

### OVOS voice bot

Answer a call and transcribe the caller with an [OVOS](https://openvoiceos.org) STT/VAD pipeline,
using the incoming call audio as a microphone source:

```python
from baresipy import BareSIP
from baresipy.ovos import BareSIPMicrophone
from ovos_plugin_manager.stt import OVOSSTTFactory
from ovos_plugin_manager.vad import OVOSVADFactory
from ovos_simple_listener import SimpleListener, ListenerCallbacks


class VoiceBot(BareSIP):
    def handle_incoming_call(self, number):
        self.accept_call()

    def handle_call_established(self):
        mic = BareSIPMicrophone(sip=self)
        SimpleListener(mic=mic, wakeword=None,
                        vad=OVOSVADFactory.create(),
                        stt=OVOSSTTFactory.create(),
                        callbacks=ListenerCallbacks()).start()


bot = VoiceBot("your_user", "your_password", "your_sip_gateway.example", record_rx=True)
```

Full runnable version with two-way TTS replies: [examples/voice_bot.py](examples/voice_bot.py).
See [docs/ovos-integration.md](docs/ovos-integration.md) for the complete walkthrough.

## Examples

| Example | Demonstrates |
|---|---|
| [examples/scripted_call.py](examples/scripted_call.py) | dial out, speak, send DTMF, hang up |
| [examples/events.py](examples/events.py) | subclassing `BareSIP` to auto-answer and speak |
| [examples/voice_bot.py](examples/voice_bot.py) | two-way OVOS STT/TTS voice bot |
| [examples/voicemail.py](examples/voicemail.py) | voicemail / answering machine, with optional transcription |
| [examples/call_transfer.py](examples/call_transfer.py) | receptionist-style call transfer |
| [examples/outbound_campaign.py](examples/outbound_campaign.py) | sequential outbound dialing campaign |
| [examples/conversational_agent.py](examples/conversational_agent.py) | barge-in voice agent with a pluggable response function |
| [examples/multi_line.py](examples/multi_line.py) | concurrent multi-line SIP in one process |
| [examples/secure_trunk.py](examples/secure_trunk.py) | registered account over TLS transport + SRTP media |
| [examples/gateway_client.py](examples/gateway_client.py) | driving `baresipy-gateway` over HTTP/WebSocket |
| [examples/contact_list.py](examples/contact_list.py) | local JSON contact store |
| [examples/ivr_menu.py](examples/ivr_menu.py) | IVR menu (DTMF-driven call routing), see [docs/ivr.md](docs/ivr.md) |

See [docs/call-control.md](docs/call-control.md) for transfer, DTMF, barge-in, and call-metadata
details used across these examples.

## Features

| Feature | How |
|---|---|
| Registered SIP account calls | `BareSIP(user, pwd, gateway)` |
| Registrar-less direct SIP calls | `BareSIP()` + `call("sip:user@ip:5060")`, see [docs/direct-calls.md](docs/direct-calls.md) |
| Headless operation (no sound card) | `BareSIP(headless=True)` |
| Text-to-speech into a call | `speak()` through any [OPM](https://github.com/OpenVoiceOS/ovos-plugin-manager) TTS plugin |
| Arbitrary audio into a call | `send_audio(path)` |
| DTMF (send/receive) | `send_dtmf(digits, mode="keys")`, `handle_dtmf_received()` |
| Recording inbound call audio | `record_rx=True`, `get_rx_wav()` / `get_rx_stream()` |
| IVR phone menus | `baresipy.ivr.IVRPhone`, see [docs/ivr.md](docs/ivr.md) |
| OVOS microphone plugin | `baresipy.ovos.BareSIPMicrophone` |
| Local contact list | `baresipy.contacts.ContactList` |
| Event-driven call handling | override `handle_*` methods |

## Documentation

- [docs/setup.md](docs/setup.md): system dependencies, install, verifying with a first call, troubleshooting
- [docs/configuration.md](docs/configuration.md): config directory, `render_config`, full `BareSIP` constructor reference
- [docs/call-control.md](docs/call-control.md): transfer, DTMF, barge-in, call metadata, login retries
- [docs/direct-calls.md](docs/direct-calls.md): registrar-less/direct SIP mode
- [docs/ivr.md](docs/ivr.md): declarative IVR phone-tree menus
- [docs/ovos-integration.md](docs/ovos-integration.md): building a full OVOS voice bot
- [docs/http-gateway.md](docs/http-gateway.md): driving baresipy over HTTP/WebSocket through `baresipy-gateway`
- [docs/docker.md](docs/docker.md): container image usage and the e2e rig
- [docs/testing.md](docs/testing.md): running and writing tests

## Related projects

- [OpenVoiceOS](https://openvoiceos.org): the voice-assistant platform baresipy's optional STT/VAD/TTS pipeline is built on
- [ovos-plugin-manager](https://github.com/OpenVoiceOS/ovos-plugin-manager): the plugin factory system used to load STT, VAD, and TTS engines
- [phoonnx](https://github.com/TigreGotico/phoonnx): the default TTS engine used by `speak()`/`say()`

## Credits

This work has been sponsored by Matt Keys, [eZuce Inc](https://ezuce.com/)

## License

[MIT](LICENSE.md)
