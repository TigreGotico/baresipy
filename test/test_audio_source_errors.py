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


class TestAudioSourceErrorsSurfaceViaHook(unittest.TestCase):
    def setUp(self):
        self.bs = make_baresip()

    def test_unrecognized_errno_reaches_new_hook(self):
        line = "failed to set audio-source (Function not implemented)"
        with patch.object(self.bs, "handle_audio_source_error") as h:
            self.bs._handle_output_line(line)
        h.assert_called_once_with(
            "failed to set audio-source (Function not implemented)")

    def test_no_such_device_still_hangs_up(self):
        line = "failed to set audio-source (No such device)"
        with patch.object(self.bs, "handle_audio_stream_failure") as h:
            self.bs._handle_output_line(line)
        h.assert_called_once()

    def test_no_such_file_reaches_hook_without_hangup(self):
        line = "failed to set audio-source (No such file or directory)"
        with patch.object(self.bs, "handle_audio_source_error") as h, \
                patch.object(self.bs, "handle_audio_stream_failure") as hang:
            self.bs._handle_output_line(line)
        h.assert_called_once_with(
            "failed to set audio-source (No such file or directory)")
        hang.assert_not_called()


if __name__ == "__main__":
    unittest.main()
