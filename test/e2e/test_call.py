"""End-to-end test: spins up two real baresip processes (via docker
compose) and validates that a registrar-less call between them actually
establishes, that DTMF is delivered in at least one direction, and that
the callee's recorded rx audio leg is real (non-silent) audio - ie. this
exercises the actual baresip stdout parsing in baresipy.__init__ against a
real binary, not mocked/expected strings.

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

        assert results["call_established"] is True, (
            "call never reached ESTABLISHED on the caller side: "
            + json.dumps(results))

        # DTMF is asserted in at least one direction rather than both:
        # in-band DTMF detection depends on the codec/jitter behaviour of
        # the specific baresip build under test, so we log both directions
        # and only require that SOME DTMF got through end-to-end.
        caller_saw_dtmf = "4" in results["caller_dtmf_received"] or \
            "2" in results["caller_dtmf_received"]
        callee_saw_dtmf = "7" in callee_dtmf
        print("caller dtmf:", results["caller_dtmf_received"])
        print("callee dtmf:", callee_dtmf)
        assert caller_saw_dtmf or callee_saw_dtmf, (
            "no DTMF was observed in either direction: "
            f"caller saw {results['caller_dtmf_received']!r}, "
            f"callee saw {callee_dtmf!r}")

        assert results["rx_wav"], "callee produced no rx recording"
        assert results["rx_wav_size"] > 44, (
            "rx recording is empty (header-only)")
        assert results["rx_non_silent"] is True, (
            f"rx recording looks silent (rms={results.get('rx_rms')})")
    finally:
        subprocess.run(
            ["docker", "compose", "-f", COMPOSE_FILE, "down", "-v"],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True,
            timeout=60,
        )
        shutil.rmtree(shared_dir, ignore_errors=True)
