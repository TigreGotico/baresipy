# IVR menus (`baresipy.ivr`)

Declarative phone-tree menus on top of `BareSIP`, for building "press 1 for X, 2 for Y" style
call flows without hand-rolling DTMF state machines.

## Concepts

- `IVRNode`: one menu: a spoken `prompt` plus a mapping of DTMF digit to option.
- `IVRSession`: runs one caller through a tree of `IVRNode`s on an active call.
- `IVRPhone`: a ready-made `BareSIP` subclass that auto-answers and runs one `IVRSession` per
  call, forwarding DTMF automatically.

## `IVRNode`

```python
from baresipy.ivr import IVRNode

root = IVRNode(
    prompt="Press 1 for sales, 2 for support, 0 to hang up.",
    options={
        "1": some_submenu,           # another IVRNode
        "2": "transfer:sip:support@example.com",
        "9": my_callback,            # callable(session) -> None
        "0": "hangup",
    },
    timeout=10.0,               # seconds to wait for a digit
    invalid_prompt="Sorry, that is not a valid option.",
    timeout_prompt="Are you still there?",
    max_retries=2,               # invalid/timeout retries before fallback
    fallback=None,                # "hangup" (default) or "transfer:<uri>"
)
```

Each entry in `options` is one of:

- an **`IVRNode`**: descend into a submenu; `"back"` in the submenu returns here
- a **callable** `(session: IVRSession) -> None`: run an action (for example speak some text,
  look something up), then re-speak the current menu's prompt
- `"hangup"`: end the call
- `"transfer:<uri>"`: blind-transfer the call to `<uri>` (`BareSIP.transfer`)
- `"back"`: return to the previous menu (only meaningful inside a submenu)
- `"repeat"`: just re-speak the current prompt

If the caller presses an unmapped digit, or does not press anything before `timeout` seconds
elapse, the node speaks its `invalid_prompt`/`timeout_prompt` and repeats the prompt, up to
`max_retries` times. After that, `fallback` runs (`"hangup"` by default).

Pressing any digit interrupts (barges in on) whatever is currently playing, through
`BareSIP.stop_audio()`.

## `IVRSession`

```python
from baresipy.ivr import IVRSession

session = IVRSession(phone, root)
session.run()          # blocking; navigates the tree until hangup/transfer/call end
session.path            # -> ["1", "2"] - digits pressed so far, in order
session.stop()           # abort a running session from another thread
```

`IVRSession` only needs digits delivered to it. It does not read them off the wire itself. Feed
digits in from a `BareSIP.handle_dtmf_received` override:

```python
class MyPhone(BareSIP):
    def handle_call_established(self):
        self.session = IVRSession(self, root)
        Thread(target=self.session.run, daemon=True).start()

    def handle_dtmf_received(self, char, duration):
        super().handle_dtmf_received(char, duration)
        self.session.on_digit(char)
```

`IVRPhone` (below) does exactly this for you.

## `IVRPhone`

```python
from baresipy.ivr import IVRNode, IVRPhone

root = IVRNode(prompt="Press 1 for hours, 0 to hang up.", options={
    "1": lambda session: session.phone.speak("We are open nine to five."),
    "0": "hangup",
})

phone = IVRPhone(user, pwd, gateway, ivr=root)
```

`IVRPhone` auto-accepts every incoming call and runs a fresh `IVRSession` against `ivr` in a
daemon thread per call, ending the session automatically when the call ends.

See [examples/ivr_menu.py](../examples/ivr_menu.py) for a complete runnable demo.

---
[← Direct calls](direct-calls.md) · [Home](../README.md) · [OVOS integration →](ovos-integration.md)
