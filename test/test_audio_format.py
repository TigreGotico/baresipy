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


class TestConfigurableAudioFormat(unittest.TestCase):
    def test_send_audio_uses_custom_frame_rate_and_channels(self):
        bs = make_baresip(audio_frame_rate=8000, audio_channels=1)
        with patch.object(bs, "convert_audio") as conv, \
                patch.object(type(bs), "call_established",
                              new=property(lambda self: True)), \
                patch.object(bs, "do_command"):
            conv.return_value = ("/tmp/x.wav", 3.0)
            bs.send_audio("f.wav", block=False)
        conv.assert_called_once_with(
            "f.wav", frame_rate=8000, channels=1)

    def test_send_audio_defaults_to_48000_stereo(self):
        bs = make_baresip()
        with patch.object(bs, "convert_audio") as conv, \
                patch.object(type(bs), "call_established",
                              new=property(lambda self: True)), \
                patch.object(bs, "do_command"):
            conv.return_value = ("/tmp/x.wav", 3.0)
            bs.send_audio("f.wav", block=False)
        conv.assert_called_once_with(
            "f.wav", frame_rate=48000, channels=2)


if __name__ == "__main__":
    unittest.main()
