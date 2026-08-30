import io
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import baresipy
from baresipy.call import CallInfo
from baresipy.server import GatewayPhone, create_app


def make_fake_phone(**attrs):
    phone = MagicMock()
    phone.current_call = None
    phone.call_status = "DISCONNECTED"
    phone.call_established = False
    phone.ready = True
    phone.running = True
    for k, v in attrs.items():
        setattr(phone, k, v)
    return phone


def make_gateway_phone(**kwargs):
    """Build a real GatewayPhone with the underlying pexpect process
    mocked out, mirroring test_state_machine.make_baresip."""
    kwargs.setdefault("autostart", False)
    kwargs.setdefault("config_path", tempfile.mkdtemp())
    with patch.object(baresipy.pexpect, "spawn") as mock_spawn:
        mock_spawn.return_value = MagicMock()
        gp = GatewayPhone(**kwargs)
    return gp


class TestStatusAndCallControl(unittest.TestCase):
    def setUp(self):
        self.phone = make_fake_phone()
        self.app = create_app(phone=self.phone)
        self.client = TestClient(self.app)

    def test_status(self):
        resp = self.client.get("/status")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "DISCONNECTED")
        self.assertEqual(body["current_call"], None)
        self.assertTrue(body["ready"])
        self.assertTrue(body["running"])

    def test_call_dials(self):
        resp = self.client.post("/call", json={"uri": "sip:foo@bar"})
        self.assertEqual(resp.status_code, 200)
        self.phone.call.assert_called_once_with("sip:foo@bar")

    def test_call_conflict_when_already_in_call(self):
        self.phone.current_call = "sip:foo@bar"
        resp = self.client.post("/call", json={"uri": "sip:baz@bar"})
        self.assertEqual(resp.status_code, 409)

    def test_hangup(self):
        self.phone.current_call = "sip:foo@bar"
        resp = self.client.post("/hangup")
        self.assertEqual(resp.status_code, 200)
        self.phone.hang.assert_called_once()

    def test_hangup_no_call(self):
        resp = self.client.post("/hangup")
        self.assertEqual(resp.status_code, 409)

    def test_accept(self):
        self.phone.current_call = "sip:foo@bar"
        resp = self.client.post("/accept")
        self.assertEqual(resp.status_code, 200)
        self.phone.accept_call.assert_called_once()

    def test_accept_no_call(self):
        resp = self.client.post("/accept")
        self.assertEqual(resp.status_code, 409)

    def test_hold_resume(self):
        self.phone.current_call = "sip:foo@bar"
        self.assertEqual(self.client.post("/hold").status_code, 200)
        self.assertEqual(self.client.post("/resume").status_code, 200)
        self.phone.hold.assert_called_once()
        self.phone.resume.assert_called_once()

    def test_transfer_happy(self):
        self.phone.current_call = "sip:foo@bar"
        resp = self.client.post("/transfer", json={"uri": "sip:human@example.com"})
        self.assertEqual(resp.status_code, 200)
        self.phone.transfer.assert_called_once_with("sip:human@example.com")

    def test_transfer_no_call(self):
        resp = self.client.post("/transfer", json={"uri": "sip:human@example.com"})
        self.assertEqual(resp.status_code, 409)

    def test_stop_audio(self):
        resp = self.client.post("/stop_audio")
        self.assertEqual(resp.status_code, 200)
        self.phone.stop_audio.assert_called_once()

    def test_calls_returns_history_newest_first(self):
        older = CallInfo(uri="sip:a@b", user="a", host="b", direction="in",
                          started=1.0, ended=2.0, reason="200")
        newer = CallInfo(uri="sip:c@d", user="c", host="d", direction="out",
                          started=3.0, ended=4.0, reason="200")
        newer.call_id = "abc123"
        self.phone.call_history = [older, newer]
        resp = self.client.get("/calls")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body), 2)
        self.assertEqual(body[0]["uri"], "sip:c@d")
        self.assertEqual(body[0]["call_id"], "abc123")
        self.assertEqual(body[1]["uri"], "sip:a@b")
        self.assertIsNone(body[1]["call_id"])


class TestSpeakDtmfAudio(unittest.TestCase):
    def setUp(self):
        self.phone = make_fake_phone()
        self.app = create_app(phone=self.phone)
        self.client = TestClient(self.app)

    def test_speak_happy(self):
        self.phone.call_established = True
        resp = self.client.post("/speak", json={"text": "hello"})
        self.assertEqual(resp.status_code, 200)
        self.phone.speak.assert_called_once_with("hello")

    def test_speak_no_call(self):
        resp = self.client.post("/speak", json={"text": "hello"})
        self.assertEqual(resp.status_code, 409)

    def test_speak_no_tts_returns_503(self):
        self.phone.call_established = True
        self.phone.speak.side_effect = RuntimeError("no TTS configured")
        resp = self.client.post("/speak", json={"text": "hello"})
        self.assertEqual(resp.status_code, 503)

    def test_dtmf_invalid_mode(self):
        self.phone.call_established = True
        resp = self.client.post("/dtmf", json={"digits": "123", "mode": "bogus"})
        self.assertEqual(resp.status_code, 422)

    def test_dtmf_keys(self):
        self.phone.call_established = True
        resp = self.client.post("/dtmf", json={"digits": "123", "mode": "keys"})
        self.assertEqual(resp.status_code, 200)
        self.phone.send_dtmf.assert_called_once_with("123", "keys")

    def test_dtmf_keys_no_call(self):
        resp = self.client.post("/dtmf", json={"digits": "123", "mode": "keys"})
        self.assertEqual(resp.status_code, 409)

    def test_audio_upload_invokes_send_audio(self):
        self.phone.call_established = True
        files = {"file": ("test.wav", io.BytesIO(b"RIFF....WAVEfmt "), "audio/wav")}
        resp = self.client.post("/audio", files=files)
        self.assertEqual(resp.status_code, 200)
        self.phone.send_audio.assert_called_once()
        called_path = self.phone.send_audio.call_args[0][0]
        self.assertTrue(called_path.endswith(".wav"))

    def test_audio_upload_no_call(self):
        files = {"file": ("test.wav", io.BytesIO(b"data"), "audio/wav")}
        resp = self.client.post("/audio", files=files)
        self.assertEqual(resp.status_code, 409)


class TestAuth(unittest.TestCase):
    def setUp(self):
        self.phone = make_fake_phone()
        self.app = create_app(phone=self.phone, token="secret123")
        self.client = TestClient(self.app)

    def test_missing_token_401(self):
        resp = self.client.get("/status")
        self.assertEqual(resp.status_code, 401)

    def test_wrong_token_401(self):
        resp = self.client.get("/status", headers={"Authorization": "Bearer wrong"})
        self.assertEqual(resp.status_code, 401)

    def test_correct_token_200(self):
        resp = self.client.get("/status", headers={"Authorization": "Bearer secret123"})
        self.assertEqual(resp.status_code, 200)


class TestEventsWebsocket(unittest.TestCase):
    def test_events_stream_real_gateway_phone(self):
        gp = make_gateway_phone()
        app = create_app(phone=gp)
        client = TestClient(app)
        with client.websocket_connect("/ws/events") as ws:
            gp.handle_call_established()
            msg = ws.receive_json()
            self.assertEqual(msg["event"], "call_established")

    def test_events_backlog_sent_on_connect(self):
        gp = make_gateway_phone()
        gp.handle_login_success()
        app = create_app(phone=gp)
        client = TestClient(app)
        with client.websocket_connect("/ws/events") as ws:
            msg = ws.receive_json()
            self.assertEqual(msg["event"], "login_success")

    def test_auto_answer_accepts_incoming(self):
        gp = make_gateway_phone(auto_answer=True)
        with patch.object(gp, "accept_call") as accept:
            gp.handle_incoming_call("sip:caller@x")
            accept.assert_called_once()

    def test_no_auto_answer_waits(self):
        gp = make_gateway_phone(auto_answer=False)
        with patch.object(gp, "accept_call") as accept:
            gp.handle_incoming_call("sip:caller@x")
            accept.assert_not_called()

    def test_events_carry_call_id(self):
        gp = make_gateway_phone(auto_answer=False)
        gp.handle_incoming_call("sip:caller@x")
        call_id = gp._call_id
        self.assertIsNotNone(call_id)
        gp.handle_call_established()
        event = gp.backlog[-1]
        self.assertEqual(event["data"]["call_id"], call_id)

    def test_call_id_cleared_after_call_ended(self):
        gp = make_gateway_phone(auto_answer=False)
        gp.handle_incoming_call("sip:caller@x")
        self.assertIsNotNone(gp._call_id)
        gp.handle_call_ended("bye", "sip:caller@x")
        self.assertIsNone(gp._call_id)


class FakeRxStream:
    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.sample_rate = 16000
        self.sample_width = 2
        self.channels = 1
        self.closed = False

    def read(self, n_bytes, timeout=None):
        if self._chunks:
            return self._chunks.pop(0)
        return b""

    def close(self):
        self.closed = True


class TestAudioWebsocket(unittest.TestCase):
    def test_audio_stream_header_frames_eof(self):
        chunk = (b"\x00\x01" * 100)
        stream = FakeRxStream([chunk, b""])
        established = {"v": True}

        phone = make_fake_phone()
        phone.get_rx_stream = MagicMock(return_value=stream)
        type(phone).call_established = property(
            lambda self: established["v"])

        def flip_after_read(*a, **kw):
            established["v"] = False
            return b""

        # after the one real chunk, flip call_established so the loop ends
        orig_read = stream.read

        def read_and_maybe_end(n, timeout=None):
            data = orig_read(n, timeout)
            if not data:
                established["v"] = False
            return data
        stream.read = read_and_maybe_end

        app = create_app(phone=phone)
        client = TestClient(app)
        with client.websocket_connect("/ws/audio") as ws:
            header = ws.receive_json()
            self.assertEqual(header["sample_rate"], 16000)
            self.assertEqual(header["channels"], 1)
            frame = ws.receive_bytes()
            self.assertGreater(len(frame), 0)
            eof = ws.receive_json()
            self.assertEqual(eof["event"], "eof")

    def test_audio_stream_closes_when_no_rx_stream(self):
        phone = make_fake_phone()
        phone.get_rx_stream = MagicMock(return_value=None)
        app = create_app(phone=phone)
        client = TestClient(app)
        with self.assertRaises(Exception):
            with client.websocket_connect("/ws/audio") as ws:
                ws.receive_json()


if __name__ == "__main__":
    unittest.main()
