# Docker

Running baresipy in a container, and the two-container end-to-end call rig.

## Image

`Dockerfile` builds a `python:3.12-slim` image with the system `baresip` and `ffmpeg` packages
installed, plus `baresipy` itself (`pip install .`).

Pull the published image:

```bash
docker pull ghcr.io/tigregotico/baresipy:latest
```

Available tags: `:dev` (tracks the development branch), `:latest` (latest release), and semver
tags (for example `:1.2.3`) for pinned versions.

Build locally:

```bash
docker build -t baresipy .
```

### Installing the `[ovos]` extra in the image

By default the image installs no extras. Pass `INSTALL_EXTRAS` at build time to pull in
`ovos-plugin-manager`, `phoonnx`, and `ovos-simple-listener`:

```bash
docker build --build-arg INSTALL_EXTRAS="[ovos]" -t baresipy-ovos .
```

## Running a bot in a container

The image's default `CMD` is `python`. Mount or `COPY` your bot script and run it directly, for
example:

```bash
docker run --rm -it \
    -p 5060:5060/udp \
    -v $(pwd)/my_bot.py:/app/my_bot.py \
    baresipy python my_bot.py
```

Containers rarely have a real sound card, so bots that run in them should use `headless=True` (see
[docs/setup.md](setup.md#troubleshooting)).

### Port considerations

- **`5060/udp`** (or `/tcp`, matching your `transport`): SIP signalling. This port must be
  published and reachable for the container to register with a gateway or receive direct calls.
- **RTP range**: the actual call audio. baresip's default config does not pin a fixed RTP range
  (see the commented `#rtp_ports 10000-20000` line in the config template,
  [docs/configuration.md](configuration.md)). For containers behind NAT/port-mapping you generally
  want to set and publish an explicit range so audio can traverse it.

## The e2e rig

`docker-compose.e2e.yml` runs two registrar-less, headless baresip instances (`callee` and
`caller`) that call each other directly by static IP over a private compose network, with no SIP
registrar involved, exercising the direct-call path described in
[docs/direct-calls.md](direct-calls.md). `callee` auto-accepts and echoes back DTMF `"42"`.
`caller` dials, sends DTMF `"7"` plus a generated sine-wave wav, waits for the echo, and writes
`results.json` to a shared volume for `test/e2e/test_call.py` to assert on (call established,
DTMF received both ways, non-silent rx audio recorded).

Both services get static IPs (`172.31.99.10`/`172.31.99.11`) specifically because baresip only
accepts an incoming call whose request-URI host is one of its own local addresses. The caller
dials the callee's IP, not a docker DNS hostname.

Run it directly:

```bash
docker compose -f docker-compose.e2e.yml up --build \
    --abort-on-container-exit --exit-code-from caller
```

or through pytest, which drives the same compose command against a temp shared directory:

```bash
pytest test/ -m e2e
```

See [docs/testing.md](testing.md) for how the e2e marker fits into the rest of the test suite.

---
[← HTTP gateway](./http-gateway.md) · [Home](../README.md) · [Testing →](testing.md)
