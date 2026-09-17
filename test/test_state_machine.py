import tempfile
import unittest
from unittest.mock import patch, MagicMock

import baresipy


def make_baresip(**kwargs):
    """Create a BareSIP instance without spawning a real baresip process
    or starting the event-loop thread, and without touching the real
    ~/.baresipy config directory."""
    kwargs.setdefault("autostart", False)
    kwargs.setdefault("config_path", tempfile.mkdtemp())
    with patch.object(baresipy.pexpect, "spawn") as mock_spawn:
        mock_spawn.return_value = MagicMock()
        bs = baresipy.BareSIP(**kwargs)
    return bs


class TestStateMachineRegistrarLess(unittest.TestCase):
    def setUp(self):
        self.bs = make_baresip()

    def tearDown(self):
        # never let the real quit() touch anything - it's a mock process
        pass

    def test_ready_registrarless(self):
        with patch.object(self.bs, "handle_ready") as h:
            self.bs._handle_output_line("baresip is ready.")
        h.assert_called_once()
        self.assertTrue(self.bs.ready)

    def test_login_success(self):
        with patch.object(self.bs, "handle_login_success") as h:
            self.bs._handle_output_line(
                "All 1 useragent registered successfully!")
        h.assert_called_once()
        self.assertTrue(self.bs.ready)

    def test_login_failures(self):
        lines = [
            "ua: SIP register failed: some reason",
            "401 Unauthorized",
            "Register: Destination address required",
            "Register: Connection timed out",
        ]
        for line in lines:
            with patch.object(self.bs, "handle_login_failure") as h, \
                    patch.object(self.bs, "handle_error") as herr:
                self.bs._handle_output_line(line)
            h.assert_called_once()
            herr.assert_called_once_with(line)

    def test_incoming_call_legacy(self):
        line = "Incoming call from: sip:foo@bar - (press 'a' to accept)"
        with patch.object(self.bs, "handle_incoming_call") as h:
            self.bs._handle_output_line(line)
        h.assert_called_once_with("sip:foo@bar")
        self.assertEqual(self.bs.current_call, "sip:foo@bar")
        self.assertEqual(self.bs.call_status, "INCOMING")

    def test_incoming_call_modern_menu_form(self):
        line = ("menu: session 0: Incoming call from: sip:foo@bar AUDIO - "
                "audio-video: yes-no - (press 'a' to accept)")
        with patch.object(self.bs, "handle_incoming_call") as h:
            self.bs._handle_output_line(line)
        # current parser splits on "Incoming call from: " and then on
        # " - (press 'a' to accept)", leaving the AUDIO/audio-video
        # segment attached to the number - documenting current behaviour.
        expected = "sip:foo@bar AUDIO - audio-video: yes-no"
        h.assert_called_once_with(expected)
        self.assertEqual(self.bs.current_call, expected)

    def test_ringing(self):
        with patch.object(self.bs, "handle_call_ringing") as h:
            self.bs.current_call = "sip:x@y"
            self.bs._handle_output_line("call: SIP Progress: 180 Ringing")
        h.assert_called_once()
        self.assertEqual(self.bs.call_status, "RINGING")

    def test_outgoing(self):
        with patch.object(self.bs, "handle_call_start") as h:
            self.bs._handle_output_line("call: connecting to 'sip:x@y'...")
        h.assert_called_once()
        self.assertEqual(self.bs.call_status, "OUTGOING")
        self.assertEqual(self.bs.current_call, "sip:x@y")

    def test_established(self):
        with patch.object(self.bs, "handle_call_established") as h, \
                patch("baresipy.sleep") as mock_sleep:
            self.bs._handle_output_line("Call established:")
        h.assert_called_once()
        mock_sleep.assert_called_with(0.5)
        self.assertEqual(self.bs.call_status, "ESTABLISHED")

    def test_on_hold(self):
        self.bs._handle_output_line("call: hold sip:x@y")
        self.assertEqual(self.bs.call_status, "ON HOLD")

    def test_call_terminated_with_duration(self):
        line = "x: Call with sip:y terminated (duration: 00:00:05)"
        with patch.object(self.bs, "handle_call_timestamp") as h:
            self.bs.mic_muted = True
            self.bs._handle_output_line(line)
        h.assert_called_once_with("00:00:05")
        self.assertEqual(self.bs.call_status, "DISCONNECTED")
        self.assertFalse(self.bs.mic_muted)

    def test_session_closed(self):
        line = "sip:x: session closed: 200"
        with patch.object(self.bs, "handle_call_ended") as h:
            self.bs.mic_muted = True
            self.bs._handle_output_line(line)
        h.assert_called_once_with("200", "sip:x")
        self.assertEqual(self.bs.call_status, "DISCONNECTED")
        self.assertFalse(self.bs.mic_muted)

    def test_mic_muted_flag(self):
        with patch.object(self.bs, "handle_mic_muted") as h:
            self.bs._handle_output_line("call muted")
        h.assert_called_once()
        self.assertTrue(self.bs.mic_muted)

    def test_mic_unmuted_flag(self):
        with patch.object(self.bs, "handle_mic_unmuted") as h:
            self.bs.mic_muted = True
            self.bs._handle_output_line("call un-muted")
        h.assert_called_once()
        self.assertFalse(self.bs.mic_muted)

    def test_dtmf_legacy(self):
        with patch.object(self.bs, "handle_dtmf_received") as h:
            self.bs._handle_output_line(
                "received DTMF: '1' (duration=250)")
        h.assert_called_once_with("1", 250)

    def test_dtmf_sip_info(self):
        with patch.object(self.bs, "handle_dtmf_received") as h:
            self.bs._handle_output_line(
                "call: received SIP INFO DTMF: '2' (duration=100)")
        h.assert_called_once_with("2", 100)

    def test_dtmf_inband_end(self):
        with patch.object(self.bs, "handle_dtmf_received") as h:
            self.bs._handle_output_line(
                "received in-band DTMF event: '3' (end=1)")
        h.assert_called_once_with("3", 0)

    def test_dtmf_inband_no_end_no_event(self):
        # end=0 means the DTMF tone is still in progress; the parser
        # matches the regex but only reports on end=1, so neither
        # handler should fire (avoids duplicate events).
        with patch.object(self.bs, "handle_dtmf_received") as h, \
                patch.object(self.bs, "handle_unhandled_output") as hu:
            self.bs._handle_output_line(
                "received in-band DTMF event: '3' (end=0)")
        h.assert_not_called()
        hu.assert_not_called()

    def test_audio_source_error(self):
        line = "failed to set audio-source (Function not implemented)"
        with patch.object(self.bs, "handle_error") as h:
            self.bs._handle_output_line(line)
        h.assert_called_once_with(
            "failed to set audio-source (Function not implemented)")

    def test_stop_all(self):
        self.bs.running = True
        self.bs._handle_output_line("ua: stop all (forced=1)")
        self.assertFalse(self.bs.running)

    def test_unknown_line(self):
        with patch.object(self.bs, "handle_unhandled_output") as h:
            self.bs._handle_output_line("some random gibberish output")
        h.assert_called_once_with("some random gibberish output")


class TestCallURILogic(unittest.TestCase):
    def test_call_sip_uri_passthrough(self):
        bs = make_baresip()
        with patch.object(bs, "do_command") as h:
            bs.call("sip:foo@bar")
        h.assert_called_once_with("/dial sip:foo@bar")

    def test_call_number_with_gateway(self):
        bs = make_baresip(user="u", pwd="p", gateway="example.com")
        with patch.object(bs, "do_command") as h:
            bs.call("12345")
        h.assert_called_once_with("/dial sip:12345@example.com")

    def test_call_number_without_gateway_raises(self):
        bs = make_baresip()
        with self.assertRaises(ValueError):
            bs.call("12345")


if __name__ == "__main__":
    unittest.main()
