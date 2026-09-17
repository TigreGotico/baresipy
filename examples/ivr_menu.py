"""Declarative IVR menu demo.

Auto-answers incoming calls and runs a small phone-tree:
    1 - opening hours
    2 - a joke
    3 - transfer to a human
    0 - hang up

Required installs:
    pip install baresipy[ovos] pyjokes
"""
from time import sleep

from baresipy.ivr import IVRNode, IVRPhone, IVRSession

gateway = "your_sip.gateway.net"
user = "your_phone"
pswd = "your_password"


def opening_hours(session: IVRSession) -> None:
    # speaks static text, then the caller lands back on the root prompt
    session.phone.speak("We are open Monday to Friday, nine to five.")


def tell_joke(session: IVRSession) -> None:
    try:
        from pyjokes import get_joke  # pip install pyjokes
        joke = get_joke()
    except ImportError:
        joke = "Why did the developer quit? They didn't get arrays."
    session.phone.speak(joke)


root = IVRNode(
    prompt=(
        "Press 1 for opening hours, 2 for a joke, "
        "3 to speak to a human, 0 to end the call."
    ),
    options={
        "1": opening_hours,
        "2": tell_joke,
        "3": "transfer:sip:human@example.com",
        "0": "hangup",
    },
    fallback="hangup",
)

phone = IVRPhone(user, pswd, gateway, ivr=root)

while phone.running:
    sleep(1)
