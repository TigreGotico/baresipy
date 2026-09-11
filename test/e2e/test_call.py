"""End-to-end test: spins up two real baresip processes (via docker
compose), forced onto G.711 only (see test/e2e/_common.py), and validates
that a registrar-less call between them:

- establishes, and DTMF is delivered in both directions;
- stays up past several ends of the short headless idle silence file,
  so the idle source is re-armed on both sides;
- carries the caller's tone to the callee (the callee's rx leg has sound);
- does not echo: the callee sends only silence, so the caller's rx leg
  must be silent.

This exercises the actual baresip stdout parsing in baresipy.__init__
against a real binary, not mocked/expected strings.

Requires docker (with the `compose` plugin) to be available; skipped
otherwise. Excluded from the default test run (see pyproject.toml's
`addopts = "-m 'not e2e'"`) - run explicitly with:

    pytest test/e2e/test_call.py -m e2e
    # or
    pytest test/ -m e2e
"""
import json
import os
import shutil
import subprocess
import tempfile
from os.path import dirname, join

import pytest

pytestmark = pytest.mark.e2e

REPO_ROOT = dirname(dirname(dirname(__file__)))
COMPOSE_FILE = join(REPO_ROOT, "docker-compose.e2e.yml")


def _docker_compose_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(["docker", "compose", "version"],
                        capture_output=True, check=True, timeout=15)
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _docker_compose_available(),
                     reason="docker (with the compose plugin) is required "
                            "for the e2e call test")
def test_registrarless_call_establishes_and_exchanges_media():
    shared_dir = tempfile.mkdtemp(prefix="baresipy-e2e-")
    env = dict(os.environ)
    env["E2E_SHARED_DIR"] = shared_dir

    try:
        result = subprocess.run(
            ["docker", "compose", "-f", COMPOSE_FILE, "up", "--build",
             "--abort-on-container-exit", "--exit-code-from", "caller"],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True,
            timeout=300,
        )
        print(result.stdout[-8000:])
        print(result.stderr[-4000:])

        results_path = join(shared_dir, "results.json")
        assert os.path.isfile(results_path), (
            "caller never wrote results.json - see compose logs above")
        with open(results_path) as f:
            results = json.load(f)

        callee_dtmf_path = join(shared_dir, "callee_dtmf.json")
        callee_dtmf = []
        if os.path.isfile(callee_dtmf_path):
            with open(callee_dtmf_path) as f:
                callee_dtmf = json.load(f).get("dtmf_received", [])

        callee_codecs_path = join(shared_dir, "callee_codecs.json")
        assert os.path.isfile(callee_codecs_path), (
            "callee never wrote callee_codecs.json - see compose logs above")
        with open(callee_codecs_path) as f:
            callee_codec_modules = json.load(f)["callee_codec_modules"]

        assert results["call_established"] is True, (
            "call never reached ESTABLISHED on the caller side: "
            + json.dumps(results))

        # the e2e config (test/e2e/_common.py) disables opus.so on both
        # instances, so the only codec either side can offer or answer is
        # G.711 (PCMU/PCMA) - the 8kHz case that used to kill ausine/aufile
        # idle audio. Assert this off the actual config each instance
        # loaded (BareSIP.config), not assumed: baresip's own stdout never
        # names the negotiated codec at any log level this build reaches.
        caller_codec_modules = results["caller_codec_modules"]
        print("caller codec modules:", caller_codec_modules)
        print("callee codec modules:", callee_codec_modules)
        for who, modules in (("caller", caller_codec_modules),
                              ("callee", callee_codec_modules)):
            assert modules["opus"] is False, (
                f"{who} loaded opus.so - the call could negotiate opus "
                f"instead of G.711: {modules!r}")
            assert modules["g711"] is True, (
                f"{who} did not load g711.so - it could not offer/answer "
                f"PCMU/PCMA at all: {modules!r}")

        # DTMF is required in both directions: the caller sends "7" and
        # the callee echoes back "42" 2s after the call establishes (see
        # callee.py), so a working G.711 call should carry both.
        caller_saw_dtmf = "4" in results["caller_dtmf_received"] or \
            "2" in results["caller_dtmf_received"]
        callee_saw_dtmf = "7" in callee_dtmf
        print("caller dtmf:", results["caller_dtmf_received"])
        print("callee dtmf:", callee_dtmf)
        assert callee_saw_dtmf, (
            f"callee never saw the caller's DTMF '7': {callee_dtmf!r}")
        assert caller_saw_dtmf, (
            "caller never saw the callee's DTMF '42': "
            f"{results['caller_dtmf_received']!r}")

        # The headless idle source is a short silence file here (see
        # test/e2e/_common.py). baresip closes a call when an aufile source
        # reaches the end of its file, so the call only survives the hold
        # if both sides re-armed the idle source.
        print("established at end:", results["established_at_end"],
              "hold_seconds:", results["hold_seconds"],
              "caller idle re-arms:", results["caller_idle_rearms"])
        assert results["established_at_end"] is True, (
            "the call did not survive past the end of the idle silence "
            "file - the idle source was not re-armed: "
            + json.dumps(results))

        callee_rx_path = join(shared_dir, "callee_rx.json")
        assert os.path.isfile(callee_rx_path), (
            "callee never wrote callee_rx.json - see compose logs above")
        with open(callee_rx_path) as f:
            callee_rx = json.load(f)
        print("callee rx:", callee_rx)
        assert callee_rx["idle_rearms"] >= 2, (
            f"callee re-armed its idle source {callee_rx['idle_rearms']} "
            "times during the hold, expected at least 2")

        # the caller's 440 Hz tone must reach the callee
        assert callee_rx["rx_wav"], "callee produced no rx recording"
        assert callee_rx["rx_wav_size"] > 44, (
            "callee rx recording is empty (header-only)")
        assert callee_rx["rx_has_sound"] is True, (
            "callee rx recording is silent - the caller's tone never "
            f"arrived (rms={callee_rx['rx_rms']})")

        # the callee sends only silence, so any sound the caller receives
        # is its own tone coming back: an echo
        assert results["rx_wav"], "caller produced no rx recording"
        assert results["rx_wav_size"] > 44, (
            "caller rx recording is empty (header-only)")
        print("caller rx rms:", results.get("rx_rms"))
        assert results["rx_has_sound"] is False, (
            "the caller received sound from a silent callee - its own "
            f"audio is echoed back (rms={results.get('rx_rms')})")
    finally:
        subprocess.run(
            ["docker", "compose", "-f", COMPOSE_FILE, "down", "-v"],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True,
            timeout=60,
        )
        shutil.rmtree(shared_dir, ignore_errors=True)
