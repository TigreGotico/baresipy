# Call control

In-call actions and events beyond the quickstart: transfer, DTMF, barge-in, call metadata, and
login retries.

## Transfer

`transfer(uri)` sends a SIP REFER (through baresip's `menu` module `/transfer` command) that
moves the active call to another destination. Override `handle_transfer_ok()`/
`handle_transfer_failed()` to react to the outcome:

```python
class Receptionist(BareSIP):
    def handle_call_established(self):
        self.speak("connecting you now")
        self.transfer("sip:support@your_sip.gateway.net")

    def handle_transfer_ok(self):
        LOG.info("transfer succeeded")

    def handle_transfer_failed(self, reason):
        self.speak("sorry, could not connect your call")
        self.hang()
```

See [examples/call_transfer.py](../examples/call_transfer.py).

## DTMF

`send_dtmf(digits, mode=...)` supports two modes:

- `mode="keys"` (recommended) presses the digit keys on the baresip console, sending real RTP
  telephone-events (RFC 4733). This is what SIP peers actually decode as DTMF.
- `mode="audio"` (default, for backward compatibility) synthesizes in-band DTMF tones and streams
  them as call audio. These tones are audible over the line, but not every peer is guaranteed to
  decode them as DTMF events.

```python
b.send_dtmf("123", mode="keys")
```

Incoming DTMF from the caller is reported through `handle_dtmf_received(char, duration)` and
appended to `current_call_info.dtmf`.

## Barge-in / interruptible speech

`speak()` splits text into sentences and checks for interruption between each one, so a caller can
cut off playback mid-response. `stop_audio()` immediately reverts the audio source, interrupting
any in-flight `send_audio()`/`speak()`, and triggers `handle_audio_interrupted()`:

```python
class Agent(BareSIP):
    def handle_audio_interrupted(self):
        LOG.info("caller interrupted playback")

    # elsewhere, e.g. from a VAD loop watching caller audio:
    def on_caller_speech_detected(self):
        self.stop_audio()
```

See [examples/conversational_agent.py](../examples/conversational_agent.py) for a full barge-in
voice agent built on an energy-based VAD over `get_rx_stream()`.

## Call metadata

`current_call_info` (a `CallInfo`) holds the active call's `uri`/`user`/`host`/`direction`/
`started`/`dtmf`, and is `None` when not in a call. When a call ends, baresipy finalizes it
(`ended`/`reason` set) and appends it to `call_history` (capped at the last 100 calls):

```python
if b.current_call_info:
    print(b.current_call_info.user, b.current_call_info.dtmf)

for call in b.call_history[-5:]:
    print(call.uri, call.direction, call.reason)
```

## Login retries

By default a registration failure calls `handle_login_failure()` immediately, which `quit()`s the
instance. Pass `max_login_retries`/`login_retry_delay` to retry instead:

```python
b = BareSIP(user, pwd, gateway, max_login_retries=3, login_retry_delay=10.0)
```

`handle_login_retry(attempt)` is called before each retry. `handle_login_failure()` still runs
once `max_login_retries` is exhausted. See
[examples/secure_trunk.py](../examples/secure_trunk.py).

## See also

- [docs/configuration.md](configuration.md): full `BareSIP` constructor reference
- [docs/direct-calls.md](direct-calls.md): registrar-less/direct SIP mode
- [docs/ovos-integration.md](ovos-integration.md): STT/VAD/TTS pipeline over `BareSIPMicrophone`

---
[← Configuration](configuration.md) · [Home](../README.md) · [Direct calls →](direct-calls.md)
