"""Declarative IVR (Interactive Voice Response) menus for `BareSIP`.

Build a tree of `IVRNode` menus and run a caller through it with
`IVRSession`, or use `IVRPhone` for a ready-made auto-answering phone that
drives one IVR tree per call.
"""
import threading
from dataclasses import dataclass, field
from time import time as _time
from typing import Callable, Dict, List, Optional, Union

from baresipy import BareSIP
from baresipy.utils.log import LOG

IVROption = Union["IVRNode", Callable[["IVRSession"], None], str]


@dataclass
class IVRNode:
    """A single menu in an IVR tree.

    `options` maps a single DTMF digit/char to one of:
        - another `IVRNode` (descend into a submenu)
        - a callable `(session) -> None` (run an action, then repeat this
          menu unless the callback itself navigates the session away)
        - `"hangup"` - end the call
        - `"transfer:<uri>"` - blind-transfer the call to `<uri>`
        - `"back"` - return to the previous menu
        - `"repeat"` - re-speak the current prompt
    """
    prompt: str
    options: Dict[str, IVROption] = field(default_factory=dict)
    timeout: float = 10.0
    invalid_prompt: str = "Sorry, that is not a valid option."
    timeout_prompt: str = "Are you still there?"
    max_retries: int = 2
    fallback: Optional[str] = None  # "hangup" | "transfer:<uri>" | None -> hangup


class IVRSession:
    """Runs one caller through a menu tree on an active call.

    Digits are delivered via `on_digit(char)`, meant to be called from a
    `BareSIP.handle_dtmf_received` hook (or `IVRPhone` does this for you).
    """

    def __init__(self, phone: BareSIP, root: IVRNode):
        self.phone = phone
        self.root = root
        self._stack: List[IVRNode] = []
        self._path: List[str] = []
        self._pending_digit: Optional[str] = None
        self._digit_event = threading.Event()
        self._stopped = False

    @property
    def path(self) -> List[str]:
        return list(self._path)

    def on_digit(self, char: str) -> None:
        """Feed a DTMF digit into the session. Interrupts any in-flight
        prompt playback (barge-in)."""
        if self._stopped:
            return
        self._pending_digit = char
        try:
            self.phone.stop_audio()
        except Exception as e:
            LOG.debug(f"stop_audio during barge-in failed: {e}")
        self._digit_event.set()

    def stop(self) -> None:
        self._stopped = True
        self._digit_event.set()

    def _call_alive(self) -> bool:
        return bool(getattr(self.phone, "call_established", False))

    def _speak(self, text: str) -> None:
        if not text:
            return
        try:
            self.phone.speak(text)
        except Exception as e:
            LOG.warning(f"IVR speak failed: {e}")

    def _wait_for_digit(self, timeout: float) -> Optional[str]:
        deadline = _time() + timeout
        while _time() < deadline:
            if self._stopped or not self._call_alive():
                return None
            if self._pending_digit is not None:
                digit = self._pending_digit
                self._pending_digit = None
                self._digit_event.clear()
                return digit
            self._digit_event.wait(min(0.1, max(deadline - _time(), 0)))
        # one last check in case a digit landed right at the deadline
        if self._pending_digit is not None:
            digit = self._pending_digit
            self._pending_digit = None
            self._digit_event.clear()
            return digit
        return None

    def _resolve(self, node: IVRNode) -> str:
        """Run a single node until it navigates elsewhere or the
        call/session ends. Returns one of "push" (a submenu was entered -
        the submenu is left on top of `self._stack`), "pop" ("back" was
        selected), or "end" (hangup/transfer/call-end/session-stop)."""
        retries = 0
        first = True
        while True:
            if self._stopped or not self._call_alive():
                return "end"
            if first:
                self._speak(node.prompt)
                first = False
            digit = self._wait_for_digit(node.timeout)
            if self._stopped or not self._call_alive():
                return "end"
            if digit is None:
                retries += 1
                if retries > node.max_retries:
                    self._fallback(node)
                    return "end"
                self._speak(node.timeout_prompt)
                first = True
                continue

            action = node.options.get(digit)
            if action is None:
                retries += 1
                if retries > node.max_retries:
                    self._fallback(node)
                    return "end"
                self._speak(node.invalid_prompt)
                first = True
                continue

            self._path.append(digit)
            retries = 0

            if action == "repeat":
                first = True
                continue
            if action == "back":
                return "pop"
            if action == "hangup":
                self._hangup()
                return "end"
            if isinstance(action, str) and action.startswith("transfer:"):
                self._transfer(action[len("transfer:"):])
                return "end"
            if isinstance(action, IVRNode):
                self._stack.append(action)
                return "push"
            if callable(action):
                try:
                    action(self)
                except Exception as e:
                    LOG.exception(f"IVR action callback failed: {e}")
                if self._stopped or not self._call_alive():
                    return "end"
                first = True
                continue
            LOG.warning(f"IVR: unrecognised option value {action!r}")
            return "end"

    def _fallback(self, node: IVRNode) -> None:
        fb = node.fallback or "hangup"
        if fb.startswith("transfer:"):
            self._transfer(fb[len("transfer:"):])
        else:
            self._hangup()

    def _hangup(self) -> None:
        try:
            self.phone.hang()
        except Exception as e:
            LOG.debug(f"IVR hangup failed: {e}")

    def _transfer(self, uri: str) -> None:
        try:
            self.phone.transfer(uri)
        except Exception as e:
            LOG.debug(f"IVR transfer failed: {e}")

    def run(self) -> None:
        """Blocking loop: navigates the menu tree until the call ends or
        the session reaches hangup/transfer."""
        self._stack = [self.root]
        while not self._stopped and self._call_alive() and self._stack:
            node = self._stack[-1]
            outcome = self._resolve(node)
            if outcome == "end":
                return
            if outcome == "pop":
                self._stack.pop()
                if not self._stack:
                    return
            # "push" leaves the new node on top of self._stack already


class IVRPhone(BareSIP):
    """Convenience `BareSIP` subclass: auto-answers and runs a given
    `IVRNode` tree per call in a daemon thread."""

    def __init__(self, *args, ivr: Optional[IVRNode] = None, **kwargs):
        self.ivr_root = ivr
        self._session: Optional[IVRSession] = None
        super().__init__(*args, **kwargs)

    def handle_incoming_call(self, number: str) -> None:
        self.accept_call()

    def handle_call_established(self) -> None:
        if self.ivr_root is None:
            LOG.warning("IVRPhone has no ivr root configured")
            return
        self._session = IVRSession(self, self.ivr_root)
        t = threading.Thread(target=self._session.run, daemon=True)
        t.start()

    def handle_call_ended(self, reason: str, number: Optional[str] = None) -> None:
        if self._session is not None:
            self._session.stop()
            self._session = None

    def handle_dtmf_received(self, char: str, duration: int) -> None:
        super().handle_dtmf_received(char, duration)
        if self._session is not None:
            self._session.on_digit(char)
