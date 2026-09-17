import tempfile
import unittest
from unittest.mock import patch, MagicMock

import baresipy
from baresipy.tts import get_default_tts


class TestGetDefaultTTS(unittest.TestCase):
    def test_returns_none_when_ovos_not_installed(self):
        # ovos-plugin-manager is not part of the test extra, so importing
        # it inside get_default_tts must fail and be handled gracefully
        result = get_default_tts()
        self.assertIsNone(result)


def make_baresip(**kwargs):
    kwargs.setdefault("autostart", False)
    kwargs.setdefault("config_path", tempfile.mkdtemp())
    with patch.object(baresipy.pexpect, "spawn") as mock_spawn:
        mock_spawn.return_value = MagicMock()
        bs = baresipy.BareSIP(**kwargs)
    return bs


class TestSpeak(unittest.TestCase):
    def test_speak_without_call_returns_without_error(self):
        bs = make_baresip()
        # no active call -> call_established is False -> early return
        bs.speak("hello")  # should not raise

    def test_speak_with_call_no_tts_raises(self):
        bs = make_baresip()
        with patch.object(
                type(bs), "call_established",
                new_callable=unittest.mock.PropertyMock) as mock_est, \
                patch("baresipy.get_default_tts", return_value=None):
            mock_est.return_value = True
            with self.assertRaises(RuntimeError):
                bs.speak("hello")


if __name__ == "__main__":
    unittest.main()
