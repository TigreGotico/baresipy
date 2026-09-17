"""Sequential outbound dialing campaign.

Dials a list of `(uri, message)` pairs one at a time, waits (with a timeout)
for each call to reach ESTABLISHED, speaks the message, hangs up, and reads
the outcome back from `call_history`. Busy/failed calls are retried once.
Prints a summary at the end.

Required installs:
    pip install baresipy[ovos]
"""
from time import sleep, time

from baresipy import BareSIP
from baresipy.utils.log import LOG

gateway = "your_sip.gateway.net"
user = "your_phone"
pswd = "your_password"

CAMPAIGN = [
    ("sip:contact_one@your_sip.gateway.net", "Hello, this is a test call."),
    ("sip:contact_two@your_sip.gateway.net", "Hello, this is a test call."),
]

ESTABLISH_TIMEOUT = 20.0
PACING_SECONDS = 2.0


def _wait_for_established(bot: BareSIP, timeout: float) -> bool:
    deadline = time() + timeout
    while time() < deadline:
        if bot.call_established:
            return True
        if bot.call_status == "DISCONNECTED" and bot.current_call is None:
            return False
        sleep(0.2)
    return False


def _dial_once(bot: BareSIP, uri: str, message: str) -> str:
    bot.call(uri)
    if not _wait_for_established(bot, ESTABLISH_TIMEOUT):
        LOG.warning("call to " + uri + " did not establish")
        return "failed"
    bot.speak(message)
    bot.hang()
    return "answered"


def run_campaign(bot: BareSIP) -> None:
    results = {}
    for uri, message in CAMPAIGN:
        outcome = _dial_once(bot, uri, message)
        if outcome == "failed":
            LOG.info("retrying " + uri)
            outcome = _dial_once(bot, uri, message)
        results[uri] = outcome
        sleep(PACING_SECONDS)

    LOG.info("=== campaign summary ===")
    for uri, outcome in results.items():
        LOG.info(f"{uri}: {outcome}")


if __name__ == "__main__":
    b = BareSIP(user, pswd, gateway, headless=True)
    run_campaign(b)
    b.quit()
