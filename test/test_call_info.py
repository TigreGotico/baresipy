import tempfile
import unittest
from unittest.mock import patch, MagicMock

import baresipy
from baresipy.call import CallInfo, parse_sip_uri


def make_baresip(**kwargs):
    kwargs.setdefault("autostart", False)
    kwargs.setdefault("config_path", tempfile.mkdtemp())
    with patch.object(baresipy.pexpect, "spawn") as mock_spawn:
        mock_spawn.return_value = MagicMock()
        bs = baresipy.BareSIP(**kwargs)
    return bs


class TestParseSipUri(unittest.TestCase):
    def test_full_uri_with_port(self):
        self.assertEqual(
            parse_sip_uri("sip:alice@example.com:5060"),
            ("alice", "example.com"))

    def test_full_uri_with_params(self):
        self.assertEqual(
            parse_sip_uri("sip:alice@example.com;transport=tcp"),
            ("alice", "example.com"))

    def test_full_uri_with_port_and_params(self):
        self.assertEqual(
            parse_sip_uri("sip:alice@example.com:5061;transport=tls"),
            ("alice", "example.com"))

    def test_bare_user_host(self):
        self.assertEqual(
            parse_sip_uri("alice@example.com"), ("alice", "example.com"))

    def test_missing_user(self):
        self.assertEqual(
            parse_sip_uri("sip:example.com"), (None, "example.com"))

    def test_empty_string(self):
        self.assertEqual(parse_sip_uri(""), (None, None))

    def test_none_like_falsy(self):
        self.assertEqual(parse_sip_uri(None), (None, None))


class TestCallInfoLifecycle(unittest.TestCase):
    def setUp(self):
        self.bs = make_baresip()

    def test_incoming_call_creates_call_info_in_direction(self):
        with patch.object(self.bs, "handle_incoming_call"):
            self.bs._handle_output_line(
                "Incoming call from: sip:bob@example.com - "
                "(press 'a' to accept)")
        info = self.bs.current_call_info
        self.assertIsNotNone(info)
        self.assertEqual(info.direction, "in")
        self.assertEqual(info.user, "bob")
        self.assertEqual(info.host, "example.com")

    def test_outgoing_call_creates_call_info_out_direction(self):
        with patch.object(self.bs, "handle_call_start"):
            self.bs._handle_output_line(
                "call: connecting to 'sip:carol@example.com'...")
        info = self.bs.current_call_info
        self.assertIsNotNone(info)
        self.assertEqual(info.direction, "out")
        self.assertEqual(info.user, "carol")
        self.assertEqual(info.host, "example.com")

    def test_dtmf_appends_to_current_call_info(self):
        with patch.object(self.bs, "handle_call_start"):
            self.bs._handle_output_line(
                "call: connecting to 'sip:carol@example.com'...")
        self.bs._handle_output_line("received DTMF: '1' (duration=250)")
        self.bs._handle_output_line("received DTMF: '2' (duration=250)")
        self.assertEqual(self.bs.current_call_info.dtmf, "12")

    def test_dtmf_without_active_call_does_not_crash(self):
        self.assertIsNone(self.bs.current_call_info)
        # should simply not append anywhere
        self.bs._handle_output_line("received DTMF: '5' (duration=250)")
        self.assertIsNone(self.bs.current_call_info)

    def test_call_end_appends_to_history_and_clears_current(self):
        with patch.object(self.bs, "handle_call_start"):
            self.bs._handle_output_line(
                "call: connecting to 'sip:carol@example.com'...")
        with patch.object(self.bs, "handle_call_timestamp"):
            self.bs._handle_output_line(
                "x: Call with sip:carol@example.com terminated "
                "(duration: 00:00:05)")
        self.assertIsNone(self.bs.current_call_info)
        self.assertEqual(len(self.bs.call_history), 1)
        entry = self.bs.call_history[0]
        self.assertEqual(entry.direction, "out")
        self.assertIsNotNone(entry.ended)
        self.assertEqual(entry.reason, "00:00:05")

    def test_session_closed_appends_to_history(self):
        with patch.object(self.bs, "handle_incoming_call"):
            self.bs._handle_output_line(
                "Incoming call from: sip:x - (press 'a' to accept)")
        with patch.object(self.bs, "handle_call_ended"):
            self.bs._handle_output_line("sip:x: session closed: 200")
        self.assertIsNone(self.bs.current_call_info)
        self.assertEqual(len(self.bs.call_history), 1)
        self.assertEqual(self.bs.call_history[0].reason, "200")

    def test_history_capped_at_100_entries(self):
        for i in range(105):
            self.bs.current_call_info = CallInfo(
                uri=f"sip:{i}@x", user=str(i), host="x",
                direction="out", started=0.0)
            self.bs._finalize_call_info(reason="done")
        self.assertEqual(len(self.bs.call_history), 100)
        # oldest entries dropped, newest kept
        self.assertEqual(self.bs.call_history[-1].user, "104")


if __name__ == "__main__":
    unittest.main()
