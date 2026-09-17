import tempfile
import unittest
from unittest.mock import patch, MagicMock

import baresipy


def make_baresip(**kwargs):
    kwargs.setdefault("autostart", False)
    kwargs.setdefault("config_path", tempfile.mkdtemp())
    with patch.object(baresipy.pexpect, "spawn") as mock_spawn:
        mock_spawn.return_value = MagicMock()
        bs = baresipy.BareSIP(**kwargs)
    return bs


class TestStopAudio(unittest.TestCase):
    def setUp(self):
        self.bs = make_baresip()
        self.bs.ready = True

    def test_stop_audio_flips_flag_and_reverts_source(self):
        with patch.object(self.bs.baresip, "sendline") as h:
            self.bs.stop_audio()
        self.assertTrue(self.bs._tx_interrupted)
        h.assert_called_once_with("/ausrc " + self.bs._default_ausrc)


class TestSendAudio(unittest.TestCase):
    def setUp(self):
        self.bs = make_baresip()
        self.bs.ready = True
        self.bs.current_call = "sip:x@y"
        self.bs._call_status = "ESTABLISHED"

    def test_blocking_exits_early_on_interruption(self):
        with patch.object(self.bs, "convert_audio",
                           return_value=("/tmp/foo.wav", 5.0)), \
                patch.object(self.bs.baresip, "sendline"), \
                patch("baresipy.sleep") as mock_sleep:
            def interrupt(*a, **kw):
                self.bs._tx_interrupted = True
            mock_sleep.side_effect = interrupt
            duration = self.bs.send_audio("foo.wav", block=True)
        self.assertEqual(duration, 5.0)
        # only one sleep(0.1) call happened before the flag broke the loop
        mock_sleep.assert_called_once_with(0.1)

    def test_blocking_completes_normally(self):
        with patch.object(self.bs, "convert_audio",
                           return_value=("/tmp/foo.wav", 0.2)), \
                patch.object(self.bs.baresip, "sendline") as h, \
                patch("baresipy.sleep"):
            duration = self.bs.send_audio("foo.wav", block=True)
        self.assertEqual(duration, 0.2)
        calls = [c.args[0] for c in h.call_args_list]
        self.assertIn("/ausrc aufile,/tmp/foo.wav", calls)
        self.assertIn("/ausrc " + self.bs._default_ausrc, calls)

    def test_non_blocking_schedules_timer(self):
        with patch.object(self.bs, "convert_audio",
                           return_value=("/tmp/foo.wav", 1.0)), \
                patch.object(self.bs.baresip, "sendline") as h, \
                patch("baresipy.threading.Timer") as mock_timer:
            timer_instance = MagicMock()
            mock_timer.return_value = timer_instance
            duration = self.bs.send_audio("foo.wav", block=False)
        self.assertEqual(duration, 1.0)
        mock_timer.assert_called_once_with(1.0, self.bs._revert_audio_source)
        self.assertTrue(timer_instance.daemon)
        timer_instance.start.assert_called_once()
        h.assert_called_once_with("/ausrc aufile,/tmp/foo.wav")

    def test_revert_audio_source_skipped_when_interrupted(self):
        self.bs._tx_interrupted = True
        with patch.object(self.bs.baresip, "sendline") as h:
            self.bs._revert_audio_source()
        h.assert_not_called()

    def test_revert_audio_source_runs_when_not_interrupted(self):
        self.bs._tx_interrupted = False
        with patch.object(self.bs.baresip, "sendline") as h:
            self.bs._revert_audio_source()
        h.assert_called_once_with("/ausrc " + self.bs._default_ausrc)


class _FakeTTS:
    def __init__(self):
        self.calls = []

    def get_tts(self, text, wav_file):
        self.calls.append(text)
        return wav_file, None


class TestSpeak(unittest.TestCase):
    def setUp(self):
        self.bs = make_baresip()
        self.bs.ready = True
        self.bs.current_call = "sip:x@y"
        self.bs._call_status = "ESTABLISHED"
        self.tts = _FakeTTS()
        self.bs.tts = self.tts

    def test_multiple_sentences_produce_multiple_send_calls(self):
        with patch.object(self.bs, "send_audio",
                           return_value=0.1) as sa, \
                patch("baresipy.sleep"):
            self.bs.speak("Hello there. How are you? Great!")
        self.assertEqual(len(self.tts.calls), 3)
        self.assertEqual(sa.call_count, 3)

    def test_interruption_between_sentences_stops_remaining(self):
        call_count = {"n": 0}

        def fake_send_audio(wav_file, block=True):
            call_count["n"] += 1
            if call_count["n"] == 1:
                self.bs._tx_interrupted = True
            return 0.1

        with patch.object(self.bs, "send_audio",
                           side_effect=fake_send_audio), \
                patch.object(self.bs, "handle_audio_interrupted") as hi, \
                patch("baresipy.sleep"):
            self.bs.speak("Sentence one. Sentence two. Sentence three.")
        self.assertEqual(call_count["n"], 1)
        hi.assert_called_once()

    def test_no_active_call_logs_and_returns(self):
        self.bs._call_status = None
        with patch.object(self.bs, "send_audio") as sa:
            self.bs.speak("hello")
        sa.assert_not_called()


class TestTransfer(unittest.TestCase):
    def setUp(self):
        self.bs = make_baresip()
        self.bs.ready = True

    def test_no_active_call_does_not_send_transfer(self):
        self.bs.current_call = None
        with patch.object(self.bs.baresip, "sendline") as h:
            self.bs.transfer("sip:target@example.com")
        h.assert_not_called()

    def test_active_call_sends_transfer_command(self):
        self.bs.current_call = "sip:x@y"
        with patch.object(self.bs.baresip, "sendline") as h:
            self.bs.transfer("sip:target@example.com")
        h.assert_called_once_with("/transfer sip:target@example.com")

    def test_transfer_ok_line_fires_hook(self):
        with patch.object(self.bs, "handle_transfer_ok") as h:
            self.bs._handle_output_line(
                "menu: transferring call abc123 to 'sip:target@example.com'")
        h.assert_called_once()

    def test_transfer_failed_line_fires_hook(self):
        with patch.object(self.bs, "handle_transfer_failed") as h:
            self.bs._handle_output_line("menu: transfer failure: 486")
        h.assert_called_once_with("menu: transfer failure: 486")

    def test_transfer_connect_error_fires_failed_hook(self):
        with patch.object(self.bs, "handle_transfer_failed") as h:
            self.bs._handle_output_line(
                "menu: transfer: connect error: some error")
        h.assert_called_once()


if __name__ == "__main__":
    unittest.main()
