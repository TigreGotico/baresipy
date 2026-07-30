# OVOS integration

Building a voice bot that answers a call, transcribes what the caller says with an
[OVOS](https://openvoiceos.org) STT/VAD pipeline, and replies with TTS.

## Install

```bash
pip install baresipy[ovos]
```

This pulls in `ovos-plugin-manager`, `phoonnx` (the default TTS engine), and
`ovos-simple-listener`. `baresipy` itself never requires these. Plain `import baresipy` always
works. `baresipy.ovos` and the default TTS lookup do need them.

You also need STT and VAD plugins, chosen for your use case. Examples:

```bash
pip install ovos-stt-plugin-fasterwhisper   # local Whisper-based STT
# or
pip install ovos-stt-plugin-server          # STT via a remote ovos-stt-server

pip install ovos-vad-plugin-silero          # or ovos-vad-plugin-webrtcvad
```

## Configuring plugins

The OVOS Plugin Manager factories (`OVOSSTTFactory`, `OVOSVADFactory`) and baresipy's own default
TTS lookup (`ovos_plugin_manager.tts.OVOSTTSFactory`) read which STT/VAD/TTS engine actually runs
from the standard OVOS config, `~/.config/mycroft/mycroft.conf`. Example snippet:

```json
{
  "stt": {
    "module": "ovos-stt-plugin-fasterwhisper",
    "ovos-stt-plugin-fasterwhisper": {"model": "base"}
  },
  "listener": {
    "VAD": {"module": "ovos-vad-plugin-silero"}
  },
  "tts": {
    "module": "ovos-tts-plugin-phoonnx"
  }
}
```

Swap plugins by editing this file, not your bot's python code. The factories pick up whatever is
configured at runtime.

## `BareSIPMicrophone`

`baresipy.ovos.BareSIPMicrophone` (an OPM `Microphone` plugin) tails the audio a caller sent
during an active call and feeds it to any OVOS listener component. It requires the `BareSIP`
instance it wraps to have been constructed with `record_rx=True`, so baresip's `sndfile` module
records the rx leg to disk as the call happens:

```python
from baresipy import BareSIP
from baresipy.ovos import BareSIPMicrophone

sip = BareSIP(record_rx=True, headless=True)
mic = BareSIPMicrophone(sip=sip)
```

`mic.start()` blocks until `sip.call_established`, then opens a `WavTailReader` on the newest
rx recording. `mic.read_chunk()` reads and resamples audio to `sample_rate=16000` (default),
16-bit mono PCM, the format OVOS listener components expect, regardless of the call's actual
codec rate.

## Wiring `SimpleListener`

`ovos_simple_listener.SimpleListener` drives STT/VAD over a `Microphone` and calls back on
transcribed utterances:

```python
from ovos_plugin_manager.stt import OVOSSTTFactory
from ovos_plugin_manager.vad import OVOSVADFactory
from ovos_simple_listener import SimpleListener, ListenerCallbacks


class Callbacks(ListenerCallbacks):
    @classmethod
    def text_callback(cls, utterance, lang):
        print("caller said:", utterance)


listener = SimpleListener(
    mic=mic, wakeword=None,
    vad=OVOSVADFactory.create(),
    stt=OVOSSTTFactory.create(),
    callbacks=Callbacks(),
)
listener.start()
```

`wakeword=None` means the listener activates on VAD (voice activity) alone, with no wake word
required. This suits a phone call, where the caller is always addressing the bot.

## End-to-end example

`examples/voice_bot.py` combines all of the above: a `BareSIP` subclass that accepts inbound
calls, starts a `SimpleListener` over a `BareSIPMicrophone` once the call is established, echoes
transcribed speech back through `speak()`, and stops the listener when the call ends. Run it with:

```bash
pip install baresipy[ovos] ovos-stt-plugin-server ovos-vad-plugin-webrtcvad
python examples/voice_bot.py
```

Edit the `gateway`/`user`/`pswd` placeholders at the top of the file first, or adapt it to
registrar-less mode per [docs/direct-calls.md](direct-calls.md).

## TTS

`speak()`/`say()` need an OPM TTS instance. Pass one explicitly through `BareSIP(tts=...)`, or let
baresipy create the default lazily (`ovos-tts-plugin-phoonnx`, from the `phoonnx` package) the
first time `speak()`/`say()` runs without a `tts=` configured. Any object exposing
`get_tts(text, wav_file) -> (wav_file, phonemes)` works, so you can swap in any OPM-compatible TTS
plugin.

## Latency and audio quality notes

SIP calls typically run at narrowband (8kHz, for example G.711/PCMU) or wideband (16kHz+) sample
rates, depending on the negotiated codec and peer. baresip's default config enables Opus
(variable, up to 48kHz) and G.711 (8kHz). `BareSIPMicrophone` always resamples to 16kHz mono
through `baresipy.audio.resample_pcm16` (pure stdlib, no `audioop`/numpy) before handing chunks to
the listener, since that is the rate most STT/VAD plugins expect. Narrowband (8kHz) source audio
is upsampled and does not gain detail it never had, so STT accuracy on 8kHz legs is inherently
lower than on wideband calls.

The pipeline has inherent latency: baresip must decode and write each frame to the `sndfile`
recording, `WavTailReader` polls for new bytes, and STT/VAD run on buffered chunks rather than a
true low-latency stream. Expect turn-taking on the order of seconds, not milliseconds. This is
normal for this architecture.

## See also

[docs/http-gateway.md](http-gateway.md) exposes a `BareSIP` phone over HTTP/WebSocket instead of
embedding it directly in a python process. Its `/ws/audio` route streams the same resampled
16kHz mono PCM audio `BareSIPMicrophone` reads internally, for consumers outside this process.

---
[← IVR menus](ivr.md) · [Home](../README.md) · [HTTP gateway →](./http-gateway.md)
