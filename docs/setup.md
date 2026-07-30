# Setup

Install the system and python dependencies, get SIP credentials, and make a first call.

## System dependencies

baresipy drives the real `baresip` binary as a subprocess (through `pexpect`), and uses `ffmpeg`
(through `pydub`) to convert and resample audio before sending it into a call. Install both
system-wide before you run `pip install baresipy`.

### Debian / Ubuntu

```bash
sudo apt-get update
sudo apt-get install -y baresip ffmpeg
```

### Arch Linux

```bash
sudo pacman -S baresip ffmpeg
```

### Fedora

```bash
sudo dnf install -y baresip ffmpeg
```

Confirm the binary is on `PATH`:

```bash
baresip -h
```

## Python install

```bash
pip install baresipy
```

or with [uv](https://github.com/astral-sh/uv):

```bash
uv pip install baresipy
```

### Extras

| extra | installs | needed for |
|---|---|---|
| `baresipy[ovos]` | `ovos-plugin-manager`, `phoonnx`, `ovos-simple-listener` | `speak()`/`say()` default TTS engine, `baresipy.ovos.BareSIPMicrophone`, voice bots (see [docs/ovos-integration.md](ovos-integration.md)) |
| `baresipy[test]` | `pytest`, `pytest-cov` | running the test suite (see [docs/testing.md](testing.md)) |

`baresipy` itself never requires `ovos-plugin-manager`. Plain `import baresipy` works
without it. `import baresipy.ovos` (or calling `speak()`/`say()` without passing `tts=`) raises an
`ImportError` naming the `[ovos]` extra if the dependency is missing.

## SIP account requirements

`BareSIP(user, pwd, gateway, transport="udp")` registers the account:

```
sip:<user>@<gateway>;transport=<transport>;auth_pass=<pwd>
```

- **`user`**: the SIP username/extension your provider or PBX gave you (for example `1001`).
- **`pwd`**: the SIP account password/secret for that user.
- **`gateway`**: the SIP registrar/proxy host, for example `sip.example.com` or an IP address.
  Once registered, a bare `call(number)` target resolves against this gateway
  (`sip:<number>@<gateway>`). Pass a full `sip:` URI to `call()` to dial elsewhere.
- **`transport`**: `"udp"` (default) or `"tcp"`. It must match what your provider expects.

If you do not have a SIP account, you do not need one. See
[docs/direct-calls.md](direct-calls.md) for registrar-less peer-to-peer calling.

`login_options` lets you append extra SIP URI parameters to the registration line, for example
`login_options="transport=tls"`-style flags your provider requires beyond the basics.

### Connecting to a real phone number

To place or receive calls over the public phone network, sign up with a SIP trunk provider, or
use a SIP account issued by a PBX/business phone system. They give you the same three values
baresipy needs: a SIP `user`, a `pwd`, and a `gateway` host, plus, usually, the transport they
expect (`udp`, `tcp`, or TLS).

For providers that require an encrypted trunk, use `transport="tls"` and point `sip_cafile` at a
CA bundle to verify the server certificate. Combine it with `media_encryption="srtp"` to encrypt
the call audio itself:

```python
b = BareSIP(user, pwd, gateway, transport="tls",
            sip_cafile="/etc/ssl/certs/ca-certificates.crt",
            media_encryption="srtp")
```

See [examples/secure_trunk.py](../examples/secure_trunk.py) and
[docs/call-control.md](call-control.md) for the retry/login kwargs useful when a trunk is
temporarily unreachable.

## Verifying with a first call

```python
from baresipy import BareSIP
from time import sleep

b = BareSIP("your_user", "your_password", "your_sip_gateway.example", debug=True)
b.call("some_number_or_user@your_sip_gateway.example")

while b.running:
    sleep(0.5)
    if b.call_established:
        b.speak("hello world")
        b.hang()
        b.quit()
        break
```

`debug=True` logs every raw line baresip prints. This is the fastest way to see what is actually
happening (registration, ringing, codec negotiation, hangup reason) while you get a first call
working.

## Troubleshooting

**No sound card / running on a server or in a container**: pass `headless=True`. This swaps
baresip's audio source for `ausine` (a synthesized sine tone) and its player for `aufile`
(writes to `/dev/null`), so no ALSA/PulseAudio device is required. Servers, containers, and voice
bots all use this mode. See [docs/docker.md](docker.md).

**`failed to set audio-source (Function not implemented)`** (or `No such device`): baresip
tried to open a real sound driver that is not available in the environment. Either install or fix
the audio stack, or switch to `headless=True`. `BareSIP.handle_error()` treats
`"failed to set audio-source (No such device)"` as an audio-stream failure and hangs up the call
automatically. Other audio-source errors are only logged, so watch for them with `debug=True`.

**Login failures**: `BareSIP.handle_login_failure()` runs (and, by default, calls `quit()` on
the instance) whenever baresip logs `ua: SIP register failed:`, `401 Unauthorized`,
`Register: Destination address required`, or `Register: Connection timed out`. Check
`user`/`pwd`/`gateway`/`transport` against what your provider issued, and run with `debug=True`
to see the exact rejection line.

**NAT / firewall**: baresip needs inbound UDP (or TCP, matching `transport`) on port `5060` for
SIP signalling, plus an RTP port range for the actual audio (baresip's default config listens on
an ephemeral range; see the commented `#rtp_ports 10000-20000` line in
[docs/configuration.md](configuration.md)). If calls register but audio never flows, or inbound
calls never arrive, check that both are reachable through any firewall/NAT between the machine
and the SIP gateway or peer.

---
[Home](../README.md) · [Configuration →](configuration.md)
