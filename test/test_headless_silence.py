"""Headless idle audio: a silence wav played through aufile.so, re-armed
before it runs out.

baresip 1.x has no silent audio source that works at every codec rate:
ausine.so is 48kHz only (issue #60), aubridge.so sends the remote party its
own voice back, and aufile.so closes the call at the end of the file. So
headless BareSIP plays silence through aufile.so and points the source at
the file again shortly before it ends, for as long as the call is up.
"""
import os
import tempfile
import unittest
import wave
from os.path import getmtime, isfile, join
from unittest.mock import MagicMock, patch

import baresipy
from baresipy.config import (SILENCE_FRAME_RATE, SILENCE_SECONDS,
                             ensure_silence_wav, headless_audio_source,
                             render_config)


def make_baresip(**kwargs):
    kwargs.setdefault("autostart", False)
    kwargs.setdefault("config_path", tempfile.mkdtemp())
    with patch.object(baresipy.pexpect, "spawn") as mock_spawn:
        mock_spawn.return_value = MagicMock()
        bs = baresipy.BareSIP(**kwargs)
    return bs


class TestSilenceWav(unittest.TestCase):
    def test_writes_mono_16bit_8khz_silence_of_the_given_length(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = ensure_silence_wav(tmpdir, seconds=3)
            with wave.open(path, "rb") as w:
                self.assertEqual(w.getnchannels(), 1)
                self.assertEqual(w.getsampwidth(), 2)
                self.assertEqual(w.getframerate(), SILENCE_FRAME_RATE)
                self.assertEqual(w.getnframes(), 3 * SILENCE_FRAME_RATE)
                self.assertEqual(set(w.readframes(w.getnframes())), {0})

    def test_default_length(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = ensure_silence_wav(tmpdir)
            with wave.open(path, "rb") as w:
                self.assertEqual(w.getnframes(),
                                 SILENCE_SECONDS * SILENCE_FRAME_RATE)

    def test_an_existing_matching_file_is_kept(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = ensure_silence_wav(tmpdir, seconds=2)
            os.utime(path, (1, 1))
            self.assertEqual(ensure_silence_wav(tmpdir, seconds=2), path)
            self.assertEqual(getmtime(path), 1)

    def test_a_file_of_the_wrong_length_is_rewritten(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = ensure_silence_wav(tmpdir, seconds=2)
            ensure_silence_wav(tmpdir, seconds=4)
            with wave.open(path, "rb") as w:
                self.assertEqual(w.getnframes(), 4 * SILENCE_FRAME_RATE)

    def test_a_broken_file_is_rewritten(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(join(tmpdir, "silence.wav"), "wb") as f:
                f.write(b"not a wav")
            path = ensure_silence_wav(tmpdir, seconds=1)
            with wave.open(path, "rb") as w:
                self.assertEqual(w.getnframes(), SILENCE_FRAME_RATE)


class TestHeadlessConfig(unittest.TestCase):
    def test_source_is_aufile_on_the_silence_wav(self):
        config = render_config(headless=True, silence_wav="/x/silence.wav")
        self.assertIn("audio_source\t\taufile,/x/silence.wav", config)
        self.assertEqual(headless_audio_source("/x/silence.wav"),
                         "aufile,/x/silence.wav")

    def test_player_does_not_share_a_bridge_with_the_source(self):
        config = render_config(headless=True, silence_wav="/x/silence.wav")
        self.assertIn("audio_player\t\taufile,/dev/null", config)
        for line in config.splitlines():
            self.assertNotIn("aubridge,", line)
            self.assertNotEqual(line.strip(), "module\t\t\taubridge.so")
            self.assertNotEqual(line.strip(), "module\t\t\tausine.so")

    def test_without_a_path_a_default_silence_wav_is_created(self):
        with tempfile.TemporaryDirectory() as home:
            with patch.dict(os.environ, {"HOME": home}):
                config = render_config(headless=True)
            expected = join(home, ".baresipy", "silence.wav")
            self.assertTrue(isfile(expected))
            self.assertIn("audio_source\t\taufile," + expected, config)

    def test_non_headless_is_unchanged(self):
        config = render_config(audio_driver="pulse,default")
        self.assertIn("audio_source\t\tpulse,default", config)
        self.assertIn("audio_player\t\tpulse,default", config)


class TestBareSIPHeadlessSource(unittest.TestCase):
    def test_headless_writes_the_silence_wav_into_config_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bs = make_baresip(headless=True, config_path=tmpdir)
            self.assertEqual(bs._silence_wav, join(tmpdir, "silence.wav"))
            self.assertTrue(isfile(bs._silence_wav))
            self.assertEqual(bs._default_ausrc, "aufile," + bs._silence_wav)
            self.assertIn("audio_source\t\taufile," + bs._silence_wav,
                          bs.config)

    def test_silence_length_follows_the_class_attribute(self):
        class ShortIdle(baresipy.BareSIP):
            idle_silence_seconds = 3

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(baresipy.pexpect, "spawn"):
                bs = ShortIdle(headless=True, config_path=tmpdir,
                               autostart=False)
            with wave.open(bs._silence_wav, "rb") as w:
                self.assertEqual(w.getnframes(), 3 * SILENCE_FRAME_RATE)

    def test_non_headless_has_no_silence_wav(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bs = make_baresip(config_path=tmpdir, audio_driver="pulse,default")
            self.assertIsNone(bs._silence_wav)
            self.assertEqual(bs._default_ausrc, "pulse,default")
            self.assertFalse(isfile(join(tmpdir, "silence.wav")))


class _TimerSpy:
    """Stands in for threading.Timer: records each timer, starts none."""

    def __init__(self):
        self.timers = []

    def __call__(self, interval, function, args=None, kwargs=None):
        timer = MagicMock()
        timer.interval = interval
        timer.fire = lambda: function(*(args or ()), **(kwargs or {}))
        self.timers.append(timer)
        return timer


class TestIdleRearm(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.bs = make_baresip(headless=True, config_path=self.tmpdir)
        self.bs.do_command = MagicMock()
        self.spy = _TimerSpy()
        patcher = patch.object(baresipy.threading, "Timer", self.spy)
        patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = patch.object(baresipy, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def _establish(self):
        self.bs._handle_output_line("Call established: sip:peer@10.0.0.1")

    def _idle_commands(self):
        return [c for c in self.bs.do_command.call_args_list
                if c.args == ("/ausrc " + self.bs._default_ausrc,)]

    def test_call_established_schedules_a_rearm_before_the_file_ends(self):
        self._establish()
        self.assertEqual(len(self.spy.timers), 1)
        self.assertEqual(
            self.spy.timers[0].interval,
            self.bs.idle_silence_seconds - self.bs.idle_rearm_margin)
        self.assertLess(self.spy.timers[0].interval,
                        self.bs.idle_silence_seconds)
        self.spy.timers[0].start.assert_called_once()

    def test_a_rearm_points_the_source_at_the_silence_again_and_reschedules(self):
        self._establish()
        self.spy.timers[0].fire()
        self.assertEqual(len(self._idle_commands()), 1)
        self.assertEqual(len(self.spy.timers), 2)
        self.spy.timers[1].fire()
        self.assertEqual(len(self._idle_commands()), 2)

    def test_no_rearm_after_the_call_ended(self):
        self._establish()
        self.bs._handle_output_line("sip:peer@10.0.0.1: session closed: bye")
        self.spy.timers[0].fire()
        self.assertEqual(self._idle_commands(), [])

    def test_no_rearm_after_the_call_terminated(self):
        self._establish()
        self.bs._handle_output_line(
            "Call with sip:peer@10.0.0.1 terminated (duration: 5 sec)")
        self.spy.timers[0].fire()
        self.assertEqual(self._idle_commands(), [])

    def test_a_superseded_timer_does_nothing(self):
        self._establish()
        self.spy.timers[0].fire()   # re-arms and schedules timer 1
        self.spy.timers[0].fire()   # stale: timer 1 replaced it
        self.assertEqual(len(self._idle_commands()), 1)

    def test_send_audio_cancels_the_pending_rearm_and_rearms_after(self):
        self._establish()
        wav = join(self.tmpdir, "tone.wav")
        with patch.object(self.bs, "convert_audio", return_value=(wav, 0.4)):
            self.bs.send_audio(wav, block=True)
        commands = [c.args[0] for c in self.bs.do_command.call_args_list]
        self.assertIn("/ausrc aufile," + wav, commands)
        self.assertEqual(commands[-1], "/ausrc " + self.bs._default_ausrc)
        # the timer from call setup is stale now; firing it does nothing
        before = len(self._idle_commands())
        self.spy.timers[0].fire()
        self.assertEqual(len(self._idle_commands()), before)
        # the revert scheduled a fresh re-arm
        self.spy.timers[-1].fire()
        self.assertEqual(len(self._idle_commands()), before + 1)

    def test_a_pending_rearm_does_not_cut_off_playback(self):
        self._establish()
        wav = join(self.tmpdir, "tone.wav")
        with patch.object(self.bs, "convert_audio", return_value=(wav, 30.0)):
            self.bs.send_audio(wav, block=False)
        before = len(self._idle_commands())
        self.spy.timers[0].fire()   # the call-setup re-arm, now stale
        self.assertEqual(len(self._idle_commands()), before)

    def test_stop_audio_rearms_the_silence(self):
        self._establish()
        self.bs.stop_audio()
        self.assertEqual(len(self._idle_commands()), 1)
        self.spy.timers[-1].fire()
        self.assertEqual(len(self._idle_commands()), 2)

    def test_non_headless_schedules_no_rearm(self):
        bs = make_baresip(config_path=tempfile.mkdtemp(),
                          audio_driver="pulse,default")
        bs.do_command = MagicMock()
        bs._handle_output_line("Call established: sip:peer@10.0.0.1")
        bs.stop_audio()
        self.assertEqual(self.spy.timers, [])
        bs.do_command.assert_called_once_with("/ausrc pulse,default")


if __name__ == "__main__":
    unittest.main()
