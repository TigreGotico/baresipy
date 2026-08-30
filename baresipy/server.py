"""FastAPI HTTP/WebSocket gateway around a `BareSIP` instance.

This module is only usable with the `baresipy[server]` extra installed
(`fastapi`, `uvicorn`, `python-multipart`) — plain `import baresipy` never
requires it. See docs/http-gateway.md for the full endpoint reference.
"""
import argparse
import asyncio
import os
import tempfile
import time
import uuid
from collections import deque
from dataclasses import asdict
from os.path import isfile
from typing import Any, Deque, Dict, List, Optional

from baresipy import BareSIP
from baresipy.audio import resample_pcm16

try:
    from fastapi import (Depends, FastAPI, File, Header, HTTPException,
                          UploadFile, WebSocket, WebSocketDisconnect,
                          status)
    from pydantic import BaseModel
except ImportError as e:  # pragma: no cover - exercised via test_import.py
    raise ImportError(
        "baresipy.server requires the optional 'server' extra - "
        "install with `pip install baresipy[server]`"
    ) from e


_EVENT_BACKLOG = 50


class GatewayPhone(BareSIP):
    """`BareSIP` subclass that turns call-lifecycle hooks into a queue of
    structured events, and optionally auto-accepts inbound calls."""

    def __init__(self, *args, auto_answer: bool = True,
                 loop: Optional[asyncio.AbstractEventLoop] = None,
                 **kwargs):
        self.auto_answer = auto_answer
        self._loop = loop
        self._events: Deque[Dict[str, Any]] = deque(maxlen=_EVENT_BACKLOG)
        self._subscribers: List[asyncio.Queue] = []
        self._call_id: Optional[str] = None
        super().__init__(*args, **kwargs)

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def _emit(self, event: str, data: Optional[dict] = None) -> None:
        data = dict(data or {})
        data.setdefault("call_id", self._call_id)
        payload = {"event": event, "data": data, "ts": time.time()}
        self._events.append(payload)
        loop = self._loop
        for q in list(self._subscribers):
            if loop is not None:
                loop.call_soon_threadsafe(q.put_nowait, payload)
            else:
                try:
                    q.put_nowait(payload)
                except Exception:
                    pass

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    @property
    def backlog(self) -> List[Dict[str, Any]]:
        return list(self._events)

    def _new_call_id(self) -> str:
        self._call_id = uuid.uuid4().hex
        if self.current_call_info is not None:
            self.current_call_info.call_id = self._call_id
        return self._call_id

    # hooks
    def handle_incoming_call(self, number: str) -> None:
        self._new_call_id()
        self._emit("incoming_call", {"number": number})
        if self.auto_answer:
            self.accept_call()

    def handle_call_start(self) -> None:
        self._new_call_id()

    def handle_call_established(self) -> None:
        self._emit("call_established", {"number": self.current_call})

    def handle_call_ended(self, reason: str, number: Optional[str] = None) -> None:
        self._emit("call_ended", {"reason": reason, "number": number})
        self._call_id = None

    def handle_dtmf_received(self, char: str, duration: int) -> None:
        super().handle_dtmf_received(char, duration)
        self._emit("dtmf_received", {"char": char, "duration": duration})

    def handle_login_success(self) -> None:
        self._emit("login_success", {})

    def handle_login_failure(self) -> None:
        self._emit("login_failure", {})


class CallRequest(BaseModel):
    uri: str


class TransferRequest(BaseModel):
    uri: str


class SpeakRequest(BaseModel):
    text: str


class DtmfRequest(BaseModel):
    digits: str
    mode: str = "keys"


def create_app(phone: Optional[BareSIP] = None, *,
                token: Optional[str] = None) -> FastAPI:
    """Build the FastAPI app.

    `phone` is dependency-injected primarily for tests; when omitted a
    `GatewayPhone` is not created here (use `main()` for a full CLI-driven
    run).
    """
    token = token if token is not None else os.environ.get("BARESIPY_TOKEN")

    app = FastAPI(title="baresipy gateway")
    app.state.phone = phone

    def get_phone() -> BareSIP:
        p = app.state.phone
        if p is None:
            raise HTTPException(status_code=503, detail="phone not configured")
        return p

    async def check_auth(authorization: Optional[str] = Header(default=None)) -> None:
        if not token:
            return
        expected = f"Bearer {token}"
        if authorization != expected:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                 detail="invalid or missing bearer token")

    def _no_call() -> HTTPException:
        return HTTPException(status_code=409, detail="no active call")

    def _already_in_call() -> HTTPException:
        return HTTPException(status_code=409, detail="already in a call")

    @app.get("/status", dependencies=[Depends(check_auth)])
    async def get_status(phone: BareSIP = Depends(get_phone)):
        return {
            "status": phone.call_status,
            "current_call": phone.current_call,
            "ready": bool(getattr(phone, "ready", False)),
            "running": bool(getattr(phone, "running", False)),
        }

    @app.post("/call", dependencies=[Depends(check_auth)])
    async def post_call(req: CallRequest, phone: BareSIP = Depends(get_phone)):
        if phone.current_call or phone.call_established:
            raise _already_in_call()
        await asyncio.to_thread(phone.call, req.uri)
        return {"ok": True}

    @app.post("/accept", dependencies=[Depends(check_auth)])
    async def post_accept(phone: BareSIP = Depends(get_phone)):
        if not phone.current_call:
            raise _no_call()
        await asyncio.to_thread(phone.accept_call)
        return {"ok": True}

    @app.post("/hangup", dependencies=[Depends(check_auth)])
    async def post_hangup(phone: BareSIP = Depends(get_phone)):
        if not phone.current_call:
            raise _no_call()
        await asyncio.to_thread(phone.hang)
        return {"ok": True}

    @app.post("/hold", dependencies=[Depends(check_auth)])
    async def post_hold(phone: BareSIP = Depends(get_phone)):
        if not phone.current_call:
            raise _no_call()
        await asyncio.to_thread(phone.hold)
        return {"ok": True}

    @app.post("/resume", dependencies=[Depends(check_auth)])
    async def post_resume(phone: BareSIP = Depends(get_phone)):
        if not phone.current_call:
            raise _no_call()
        await asyncio.to_thread(phone.resume)
        return {"ok": True}

    @app.post("/transfer", dependencies=[Depends(check_auth)])
    async def post_transfer(req: TransferRequest, phone: BareSIP = Depends(get_phone)):
        if not phone.current_call:
            raise _no_call()
        await asyncio.to_thread(phone.transfer, req.uri)
        return {"ok": True}

    @app.post("/stop_audio", dependencies=[Depends(check_auth)])
    async def post_stop_audio(phone: BareSIP = Depends(get_phone)):
        await asyncio.to_thread(phone.stop_audio)
        return {"ok": True}

    @app.get("/calls", dependencies=[Depends(check_auth)])
    async def get_calls(phone: BareSIP = Depends(get_phone)):
        history = list(getattr(phone, "call_history", []) or [])
        out = []
        for info in reversed(history):
            try:
                item = asdict(info)
            except TypeError:
                item = dict(getattr(info, "__dict__", {}))
            item.setdefault("call_id", getattr(info, "call_id", None))
            out.append(item)
        return out

    @app.post("/speak", dependencies=[Depends(check_auth)])
    async def post_speak(req: SpeakRequest, phone: BareSIP = Depends(get_phone)):
        if not phone.call_established:
            raise _no_call()
        try:
            await asyncio.to_thread(phone.speak, req.text)
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        return {"ok": True}

    @app.post("/dtmf", dependencies=[Depends(check_auth)])
    async def post_dtmf(req: DtmfRequest, phone: BareSIP = Depends(get_phone)):
        if req.mode not in ("keys", "audio"):
            raise HTTPException(status_code=422, detail="mode must be 'keys' or 'audio'")
        if req.mode == "keys" and not phone.call_established:
            raise _no_call()
        await asyncio.to_thread(phone.send_dtmf, req.digits, req.mode)
        return {"ok": True}

    @app.post("/audio", dependencies=[Depends(check_auth)])
    async def post_audio(file: UploadFile = File(...),
                          phone: BareSIP = Depends(get_phone)):
        if not phone.call_established:
            raise _no_call()
        suffix = ""
        if file.filename and "." in file.filename:
            suffix = "." + file.filename.rsplit(".", 1)[-1]
        data = await file.read()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(data)
            tmp_path = f.name
        try:
            await asyncio.to_thread(phone.send_audio, tmp_path)
        finally:
            if isfile(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        return {"ok": True}

    @app.websocket("/ws/events")
    async def ws_events(websocket: WebSocket):
        if token:
            auth = websocket.headers.get("authorization")
            if auth != f"Bearer {token}":
                await websocket.close(code=4001)
                return
        phone = app.state.phone
        await websocket.accept()
        q: Optional[asyncio.Queue] = None
        try:
            if hasattr(phone, "backlog"):
                for event in phone.backlog:
                    await websocket.send_json(event)
            if hasattr(phone, "subscribe"):
                if hasattr(phone, "set_loop"):
                    phone.set_loop(asyncio.get_running_loop())
                q = phone.subscribe()
                while True:
                    event = await q.get()
                    await websocket.send_json(event)
            else:
                # nothing to stream, keep the connection open until closed
                while True:
                    await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            if q is not None and hasattr(phone, "unsubscribe"):
                phone.unsubscribe(q)

    @app.websocket("/ws/audio")
    async def ws_audio(websocket: WebSocket):
        if token:
            auth = websocket.headers.get("authorization")
            if auth != f"Bearer {token}":
                await websocket.close(code=4001)
                return
        phone = app.state.phone
        get_stream = getattr(phone, "get_rx_stream", None)
        if get_stream is None:
            await websocket.accept()
            await websocket.close(code=4003)
            return
        stream = await asyncio.to_thread(get_stream)
        if stream is None:
            await websocket.accept()
            await websocket.close(code=4003)
            return

        await websocket.accept()
        dst_rate = 16000
        await websocket.send_json({
            "sample_rate": dst_rate,
            "sample_width": 2,
            "channels": 1,
        })
        try:
            while True:
                if not getattr(phone, "call_established", True):
                    break
                chunk = await asyncio.to_thread(stream.read, 4096, 1.0)
                if not chunk:
                    if not getattr(phone, "call_established", True):
                        break
                    continue
                pcm = resample_pcm16(chunk, stream.sample_rate or dst_rate,
                                      stream.channels or 1, dst_rate)
                if pcm:
                    await websocket.send_bytes(pcm)
        except WebSocketDisconnect:
            return
        finally:
            try:
                stream.close()
            except Exception:
                pass
        await websocket.send_json({"event": "eof"})

    return app


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a baresipy HTTP/WebSocket gateway")
    parser.add_argument("--user", default=None)
    parser.add_argument("--pwd", default=None)
    parser.add_argument("--gateway", default=None)
    parser.add_argument("--transport", default="udp")
    parser.add_argument("--headless", action="store_true", default=False)
    parser.add_argument("--record-rx", dest="record_rx",
                         action="store_true", default=True)
    parser.add_argument("--no-record-rx", dest="record_rx",
                         action="store_false")
    parser.add_argument("--auto-answer", dest="auto_answer",
                         action="store_true", default=True)
    parser.add_argument("--no-auto-answer", dest="auto_answer",
                         action="store_false")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--token", default=None)
    args = parser.parse_args()

    import uvicorn

    phone = GatewayPhone(user=args.user, pwd=args.pwd, gateway=args.gateway,
                          transport=args.transport, headless=args.headless,
                          record_rx=args.record_rx,
                          auto_answer=args.auto_answer, block=False)
    token = args.token or os.environ.get("BARESIPY_TOKEN")
    app = create_app(phone=phone, token=token)

    @app.on_event("startup")
    async def _bind_loop() -> None:
        phone.set_loop(asyncio.get_running_loop())

    try:
        uvicorn.run(app, host=args.host, port=args.port)
    finally:
        phone.quit()


if __name__ == "__main__":
    main()
