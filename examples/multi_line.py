"""Concurrent multi-line SIP.

Runs several registrar-less `BareSIP` instances in one process, each bound
to its own `config_path` and SIP port, so they don't collide. Each line
auto-answers with a greeting that includes its own line id.

The `sip_listen` config patch below mirrors the pattern used by
`test/e2e/_common.py::headless_config_with_sip_listen` to make each instance
bind a distinct address instead of baresip's default.

Required installs:
    pip install baresipy[ovos]
"""
from os import makedirs
from os.path import isdir, join
from time import sleep

from baresipy import BareSIP
from baresipy.config import render_config
from baresipy.utils.log import LOG

LINES = [
    {"id": "line1", "config_path": "~/.baresipy_line1", "port": 5061},
    {"id": "line2", "config_path": "~/.baresipy_line2", "port": 5062},
]


def _write_config_with_port(config_path: str, port: int) -> None:
    """Pre-write a headless config binding `sip_listen` to a distinct port,
    so BareSIP's constructor (which loads an existing config as-is) picks it
    up instead of the default."""
    expanded = config_path
    if not isdir(expanded):
        makedirs(expanded, exist_ok=True)
    cfg = render_config(headless=True)
    cfg = cfg.replace("#sip_listen\t\t0.0.0.0:5060",
                       f"sip_listen\t\t0.0.0.0:{port}")
    with open(join(expanded, "config"), "w") as f:
        f.write(cfg)


class LineBot(BareSIP):
    def __init__(self, line_id: str, *args, **kwargs):
        self.line_id = line_id
        super().__init__(*args, **kwargs)

    def handle_incoming_call(self, number: str) -> None:
        LOG.info(f"[{self.line_id}] Incoming call: {number}")
        self.accept_call()

    def handle_call_established(self) -> None:
        self.speak(f"You have reached {self.line_id}.")
        self.hang()


def main() -> None:
    from os.path import expanduser
    bots = []
    for line in LINES:
        config_path = expanduser(line["config_path"])
        _write_config_with_port(config_path, line["port"])
        bot = LineBot(line["id"], headless=True, config_path=config_path)
        bots.append(bot)

    try:
        while any(b.running for b in bots):
            sleep(0.5)
    finally:
        for b in bots:
            b.quit()


if __name__ == "__main__":
    main()
