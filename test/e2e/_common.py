"""Small helpers shared by the callee/caller e2e scripts.

Both scripts run inside their own container (see ../../docker-compose.e2e.yml)
and talk to each other purely over SIP/RTP - the only side-channel is a
bind-mounted /shared volume, used for status breadcrumbs and the final
results.json written by the caller.
"""
import json
import time
from os import makedirs
from os.path import join, isdir

from baresipy.config import render_config

SHARED = "/shared"


def write_status(name: str, msg: str) -> None:
    if not isdir(SHARED):
        makedirs(SHARED, exist_ok=True)
    line = "{ts:.3f} [{name}] {msg}\n".format(ts=time.time(), name=name,
                                               msg=msg)
    print(line, end="")
    with open(join(SHARED, name + "_status.log"), "a") as f:
        f.write(line)


def write_json(filename: str, data: dict) -> None:
    if not isdir(SHARED):
        makedirs(SHARED, exist_ok=True)
    with open(join(SHARED, filename), "w") as f:
        json.dump(data, f, indent=2)


def headless_config_with_sip_listen(config_path: str,
                                     bind: str = "0.0.0.0:5060") -> None:
    """Write a headless baresip config to `config_path/config`, patching
    `sip_listen` so the SIP UA binds an address reachable from other
    containers on the compose network (baresip's default listen address
    is not guaranteed to be the container's routable interface).
    """
    if not isdir(config_path):
        makedirs(config_path, exist_ok=True)
    cfg = render_config(headless=True)
    cfg = cfg.replace("#sip_listen\t\t0.0.0.0:5060",
                       "sip_listen\t\t" + bind)
    with open(join(config_path, "config"), "w") as f:
        f.write(cfg)
