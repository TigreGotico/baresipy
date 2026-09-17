# AGENTS.md

Guidance for agents working in this repository.

## Module layout

- `baresipy/__init__.py` — `BareSIP`, the core `Thread` subclass wrapping a `baresip` process
  via `pexpect`: registration/registrar-less login, call control, DTMF, TTS/audio playback into
  a call, rx recording, and the baresip output-line state machine (`_handle_output_line`).
- `baresipy/config.py` — the default baresip config template (`DEFAULT`) and
  `render_config()`/`ensure_sndfile_recording()`, which render/patch a config text blob
  (headless mode, sound driver, sndfile recording).
- `baresipy/audio.py` — `WavTailReader` (tails a growing baresip `sndfile` wav recording) and
  `resample_pcm16()` (pure-stdlib PCM downmix/resample, no `audioop`/numpy).
- `baresipy/ovos.py` — `BareSIPMicrophone`, an OVOS Plugin Manager `Microphone` implementation
  reading call rx audio. Lazy-imports `ovos-plugin-manager`; importing this module without the
  `[ovos]` extra installed raises `ImportError`.
- `baresipy/tts.py` — `get_default_tts()`, lazily creates a default OPM TTS plugin
  (`ovos-tts-plugin-phoonnx`) for `BareSIP.speak()`/`say()` when no `tts=` was passed.
- `baresipy/contacts.py` — `ContactList`, an optional local JSON-backed contact store, separate
  from `BareSIP`.
- `baresipy/utils/log.py` — shared `LOG` logger instance.

Full narrative docs live under `docs/` — see [README.md](README.md) for the index. Don't
duplicate that content here; keep this file focused on orientation for agents.

## Tests

Use [uv](https://github.com/astral-sh/uv):

```bash
uv venv .venv
VIRTUAL_ENV=$PWD/.venv uv pip install -e .[test]
VIRTUAL_ENV=$PWD/.venv .venv/bin/pytest test/
```

- Tests live in a single flat `test/` directory (not `tests/`).
- `pyproject.toml` sets `addopts = "-m 'not e2e'"` — the `e2e` marker (registered there) is
  excluded by default since it requires docker.
- Most tests should use the fake-`pexpect` pattern in `test/test_state_machine.py`
  (`patch.object(baresipy.pexpect, "spawn")`, `autostart=False`, a throwaway `config_path`) so
  they never spawn a real `baresip` process or touch `~/.baresipy`.
- Never skip a test because an optional dependency is missing; `baresipy` core has no optional
  deps, and `[ovos]`-only behavior is covered by `test/test_ovos_optional.py`, which asserts the
  `ImportError` message rather than being skipped.

## E2E rig

`docker-compose.e2e.yml` + `test/e2e/` spin up two real, registrar-less, headless `baresip`
processes in separate containers that call each other directly by static IP, exchange DTMF and
audio, and assert on the result. Run with `pytest test/ -m e2e` or
`docker compose -f docker-compose.e2e.yml up --build --abort-on-container-exit --exit-code-from caller`.
See [docs/docker.md](docs/docker.md) for full details. Requires docker; treat it as the
ground-truth reference for registrar-less/direct-call behavior when in doubt about how baresip's
IP-matching for incoming calls works.

## Linting

```bash
uvx ruff check .
```

`examples/` is linted along with the rest of the tree — keep example scripts syntactically valid
and import-clean even though they contain placeholder credentials.

## Project rules

- Never hand-edit `baresipy/version.py`.
- Docs (README.md, docs/, AGENTS.md) describe current behavior only — no changelog-style
  commentary, no "recently added"/"previously" framing, no version comparisons.
