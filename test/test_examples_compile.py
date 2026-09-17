"""Compile-check (not import/execute) every example script under examples/,
so a syntax error in a new example fails CI without requiring its runtime
deps (SIP gateway, ovos plugins, etc) to be installed."""
import glob
import py_compile
from os.path import dirname, join

EXAMPLES_DIR = join(dirname(dirname(__file__)), "examples")


def test_examples_compile():
    paths = sorted(glob.glob(join(EXAMPLES_DIR, "*.py")))
    assert paths, "no example scripts found under examples/"
    for path in paths:
        try:
            py_compile.compile(path, doraise=True)
        except py_compile.PyCompileError as e:
            raise AssertionError(f"{path} failed to compile: {e}") from e
