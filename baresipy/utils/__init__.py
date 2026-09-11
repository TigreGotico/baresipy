from threading import Thread
from typing import Callable, Optional

__all__ = ["create_daemon"]


def create_daemon(target: Callable, args: tuple = (),
                   kwargs: Optional[dict] = None) -> Thread:
    """Helper to quickly create and start a thread with daemon = True"""
    t = Thread(target=target, args=args, kwargs=kwargs)
    t.daemon = True
    t.start()
    return t
