"""HTTP/WebSocket client for a running `baresipy-gateway`.

Connects to /ws/events, places a call over the REST API, then prints every
event received until the call ends. See docs/http-gateway.md.

Required installs:
    pip install requests websockets

Run a gateway first, eg:
    baresipy-gateway --user your_phone --pwd your_password --gateway your_sip.gateway.net
"""
import asyncio
import json

import requests  # pip install requests
import websockets  # pip install websockets

BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000/ws/events"
CALL_URI = "sip:someone@your_sip.gateway.net"
TOKEN = None  # set to match --token/BARESIPY_TOKEN if the gateway requires auth


def _headers():
    return {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}


async def main():
    async with websockets.connect(WS_URL, additional_headers=_headers()) as ws:
        resp = requests.post(f"{BASE_URL}/call", json={"uri": CALL_URI},
                              headers=_headers())
        resp.raise_for_status()
        print("call placed:", CALL_URI)

        async for message in ws:
            event = json.loads(message)
            print(event)
            if event["event"] == "call_ended":
                break


if __name__ == "__main__":
    asyncio.run(main())
