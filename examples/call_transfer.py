"""Receptionist-style call transfer.

Auto-answers incoming calls, tells the caller they're being connected, then
transfers (SIP REFER, via `transfer()`) to a configured target URI. Overrides
`handle_transfer_ok`/`handle_transfer_failed` to log the outcome; on failure
it apologizes to the caller and hangs up instead.

Required installs:
    pip install baresipy[ovos]
"""
from time import sleep

from baresipy import BareSIP
from baresipy.utils.log import LOG

gateway = "your_sip.gateway.net"
user = "your_phone"
pswd = "your_password"

TRANSFER_TARGET = "sip:support@your_sip.gateway.net"


class ReceptionistBot(BareSIP):
    def handle_incoming_call(self, number: str) -> None:
        LOG.info("Incoming call: " + number)
        self.accept_call()

    def handle_call_established(self) -> None:
        self.speak("Please hold, connecting you now.")
        self.transfer(TRANSFER_TARGET)

    def handle_transfer_ok(self) -> None:
        LOG.info("Transfer to " + TRANSFER_TARGET + " succeeded")

    def handle_transfer_failed(self, reason: str) -> None:
        LOG.warning("Transfer to " + TRANSFER_TARGET + " failed: " + reason)
        if self.call_established:
            self.speak("Sorry, we could not connect your call. Goodbye.")
            self.hang()


if __name__ == "__main__":
    bot = ReceptionistBot(user, pswd, gateway, headless=True)
    while bot.running:
        sleep(0.5)
