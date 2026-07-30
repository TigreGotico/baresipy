# Configuration

How baresipy manages its baresip config file, and the full `BareSIP` constructor reference.

## Config directory

By default baresipy keeps its baresip config under `~/.baresipy` (override with `config_path=`).
On first run, if `~/.baresipy/config` does not exist yet, baresipy renders one from its built-in
template (`baresipy.config.DEFAULT`) through `render_config()` and writes it there. If a config
file already exists at that path, baresipy loads and uses it as-is. Only `record_rx`/`sounds_path`,
if passed, patch it further, as described below.

Whenever baresipy generates or patches the config, it first backs up whatever was there as
`~/.baresipy/config.bak`, then restores that original content when the instance `quit()`s
cleanly. A `BareSIP()` run never permanently overwrites a hand-edited config.

## `render_config()`

```python
from baresipy.config import render_config

config_text = render_config(audio_driver="alsa,default", headless=False,
                             audio_path=None, enable_sndfile=False, snd_path=None)
```

- **`audio_driver`**: value used for `audio_source`/`audio_player`/`audio_alert` when not
  headless, for example `"alsa,default"` or `"pulse,default"`.
- **`headless`**: if `True`, do not load `alsa.so`/`pulse.so` at all. Use `ausine.so`
  (synthesized sine wave) as the audio source and `aufile.so` (writing to `/dev/null`) as the
  player/alert instead, so baresip runs without any sound hardware present.
- **`audio_path`**: if a directory, patches `audio_path` to point at it (where baresip looks for
  sound prompts). If falsy but not `None`, disables sound file loading entirely
  (`audio_path /dont/load`).
- **`enable_sndfile`**: if `True`, activates the `sndfile.so` module so baresip records call
  audio (both legs) to `snd_path`. Requires `snd_path`.
- **`snd_path`**: directory to write call recordings into.

`ensure_sndfile_recording(config, snd_path)` is the lower-level helper used to patch an
*existing* config (freshly rendered or loaded from disk) to turn on `sndfile.so` recording.
The `BareSIP(record_rx=True)` kwarg uses this helper under the hood, and it works whether or not
`sndfile.so` / `snd_path` lines are already present.

## `BareSIP` constructor reference

```python
BareSIP(
    user=None, pwd=None, gateway=None, transport="udp",
    tts=None, debug=False, block=True, config_path=None,
    sounds_path=None, autostart=True, login_options=None,
    headless=False, audio_driver="alsa,default",
    record_rx=False, recording_path=None,
)
```

| kwarg | default | meaning |
|---|---|---|
| `user` | `None` | SIP username. Optional in registrar-less mode (see [docs/direct-calls.md](direct-calls.md)); used as the local account name if omitted (`"baresipy"`). |
| `pwd` | `None` | SIP account password, used to build `auth_pass=` in the registration URI. Only meaningful when `gateway` is set. |
| `gateway` | `None` | SIP registrar/proxy host. If set, baresipy registers `sip:user@gateway;transport=...;auth_pass=...` and a bare `call(number)` resolves against it. If unset, baresipy runs registrar-less (see below). |
| `transport` | `"udp"` | `"udp"` or `"tcp"`, appended to the registration URI as `;transport=...`. |
| `tts` | `None` | An OVOS Plugin Manager TTS instance (anything exposing `get_tts(text, wav_file) -> (wav_file, phonemes)`) used by `speak()`/`say()`. If `None`, baresipy lazily creates a default `ovos-tts-plugin-phoonnx` engine on first use (requires the `[ovos]` extra). |
| `debug` | `False` | Log every raw line read from the baresip process. |
| `block` | `True` | If `True`, `start()` blocks until `self.ready` becomes `True` (registration/local-UA setup complete) before returning. |
| `config_path` | `None` | Directory holding the baresip `config` file. Defaults to `~/.baresipy`. Created if missing. |
| `sounds_path` | `None` | If a directory, patches `audio_path` in the config to point at it (baresip prompt sounds). If `False`, disables sound file loading. If `None` (default), leaves the config's `audio_path` untouched. |
| `autostart` | `True` | If `True`, calls `start()` (which spawns the event-loop thread, and blocks if `block=True`) at the end of `__init__`. Set `False` to construct without starting, for example in tests. |
| `login_options` | `None` | Extra SIP URI parameters appended to the registration line (`;login_options`), for provider-specific requirements. Only applies when `gateway` is set. |
| `headless` | `False` | If `True`, render the config with `ausine`/`aufile` instead of a real sound driver, so no sound card is required. See [docs/setup.md](setup.md#troubleshooting). |
| `audio_driver` | `"alsa,default"` | Value used for the real audio source/player/alert when `headless=False`, for example `"pulse,default"`. |
| `record_rx` | `False` | Enables baresip's `sndfile` module so the audio the caller sends (rx leg) is written to disk as it happens. Required for `get_rx_wav()`/`get_rx_stream()` and for `baresipy.ovos.BareSIPMicrophone`. |
| `recording_path` | `None` | Directory `sndfile` recordings are written to when `record_rx=True`. Defaults to a fresh temp directory. |

### Other constructor kwargs used indirectly

`ContactList(database_name="contacts.db", db_dir=None)` (in `baresipy.contacts`) is a separate,
optional local JSON contact store, not wired into `BareSIP` automatically. `db_dir` defaults to
`~/.baresip`. See its docstrings and `examples/contact_list.py`.

See also [docs/call-control.md](call-control.md) for `max_login_retries`/`login_retry_delay`,
`media_encryption`, and `sip_cafile` in action.

---
[← Setup](setup.md) · [Home](../README.md) · [Call control →](call-control.md)
