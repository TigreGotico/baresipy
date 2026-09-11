# Testing

Running the unit suite, the docker e2e rig, and adding new tests.

## Unit suite

```bash
uv venv .venv
VIRTUAL_ENV=$PWD/.venv uv pip install -e .[test]
VIRTUAL_ENV=$PWD/.venv .venv/bin/pytest test/
```

or with plain `pip`:

```bash
pip install -e .[test]
pytest test/
```

`pyproject.toml` sets `addopts = "-m 'not e2e'"`, so end-to-end tests (which need docker and run
slowly) are deselected by default. Only unit tests run.

Test files, by area:

- `test/test_state_machine.py`: `BareSIP._handle_output_line()` parsing/state transitions
- `test/test_config.py`: `render_config()` / `ensure_sndfile_recording()`
- `test/test_audio.py`: `WavTailReader`
- `test/test_resample.py`: `resample_pcm16()`
- `test/test_tts.py`: `get_default_tts()`
- `test/test_contacts.py`: `ContactList`
- `test/test_import.py`, `test/test_ovos_optional.py`: import-time behavior, including that
  `import baresipy` never requires `ovos-plugin-manager`, and that `import baresipy.ovos` raises
  a clear `ImportError` naming the `[ovos]` extra when it is missing

## End-to-end rig

`test/e2e/` drives the two-container call described in [docs/docker.md](docker.md) (real
`baresip` processes, real registrar-less SIP/RTP over a docker network) and asserts on the
results:

```bash
pytest test/ -m e2e
```

This rig requires docker and docker compose. It does not run by default (see `addopts` above).

## Adding tests

Most unit tests do not need a real baresip process. Use the fake-`pexpect` pattern from
`test/test_state_machine.py` to construct a `BareSIP` instance without spawning anything or
touching `~/.baresipy`:

```python
import tempfile
from unittest.mock import patch, MagicMock
import baresipy


def make_baresip(**kwargs):
    kwargs.setdefault("autostart", False)
    kwargs.setdefault("config_path", tempfile.mkdtemp())
    with patch.object(baresipy.pexpect, "spawn") as mock_spawn:
        mock_spawn.return_value = MagicMock()
        bs = baresipy.BareSIP(**kwargs)
    return bs
```

`autostart=False` skips starting the event-loop thread. `config_path` points at a throwaway temp
directory so the test never reads or writes the real `~/.baresipy/config`. With the instance
constructed this way, feed it raw baresip output lines directly and assert on the resulting state
or on which `handle_*` method fired:

```python
bs = make_baresip()
with patch.object(bs, "handle_ready") as h:
    bs._handle_output_line("baresip is ready.")
h.assert_called_once()
assert bs.ready
```

Tests live under `test/` (a single flat test directory, not `tests/`). Mark new e2e-only tests
`@pytest.mark.e2e` (registered in `pyproject.toml`) so the default run excludes them.

---
[← Docker](docker.md) · [Home](../README.md)
