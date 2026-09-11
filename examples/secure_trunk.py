"""Registered account over a TLS + SRTP secure trunk.

Registers with `transport="tls"`, verifying the server certificate against
`sip_cafile`, and requests SRTP media encryption. Also demonstrates the
login-retry kwargs, useful when a trunk is flaky right after boot. Speaks a
test sentence once established, then hangs up.

Required installs:
    pip install baresipy[ovos]
"""
from time import sleep

from baresipy import BareSIP

gateway = "your_sip.gateway.net"
user = "your_phone"
pswd = "your_password"
sip_cafile = "/etc/ssl/certs/ca-certificates.crt"
target = "someone@your_sip.gateway.net"

b = BareSIP(
    user, pswd, gateway,
    transport="tls",
    sip_cafile=sip_cafile,
    media_encryption="srtp",
    max_login_retries=3,
    login_retry_delay=10.0,
    headless=True,
)

if b.abort:
    # registration failed even after the configured retries
    raise SystemExit(1)

b.call(target)

while b.running:
    sleep(0.5)
    if b.call_established:
        b.speak("this is a test over a secure trunk")
        b.hang()
        b.quit()
        break
