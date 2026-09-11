import tempfile
import unittest
from unittest.mock import MagicMock, patch

import baresipy
from baresipy.config import AUBRIDGE_IDLE_NAME, render_config


def make_baresip(**kwargs):
    kwargs.setdefault("autostart", False)
    kwargs.setdefault("config_path", tempfile.mkdtemp())
    with patch.object(baresipy.pexpect, "spawn") as mock_spawn:
        mock_spawn.return_value = MagicMock()
        bs = baresipy.BareSIP(**kwargs)
    return bs


class TestHeadlessAubridgeSource(unittest.TestCase):
    def test_render_config_points_at_aubridge(self):
        config = render_config(headless=True)
        self.assertIn(
            "audio_source\t\t" + AUBRIDGE_IDLE_NAME, config)
        for line in config.splitlines():
            if line.strip().startswith("audio_source"):
                self.assertNotIn("ausine", line)
                self.assertNotIn("aufile", line)

    def test_render_config_player_matches_source(self):
        config = render_config(headless=True)
        self.assertIn(
            "audio_player\t\t" + AUBRIDGE_IDLE_NAME, config)

    def test_render_config_enables_aubridge_module(self):
        config = render_config(headless=True)
        self.assertIn("module\t\t\taubridge.so", config)
        self.assertNotIn("#module\t\t\taubridge.so", config)

    def test_default_ausrc_points_at_aubridge(self):
        bs = make_baresip(headless=True)
        self.assertEqual(bs._default_ausrc, AUBRIDGE_IDLE_NAME)

    def test_non_headless_render_config_unchanged(self):
        config = render_config()
        self.assertIn("audio_source\t\talsa,default", config)
        self.assertIn("#module\t\t\taubridge.so", config)

    def test_non_headless_default_ausrc_unchanged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bs = make_baresip(config_path=tmpdir, audio_driver="pulse,default")
            self.assertEqual(bs._default_ausrc, "pulse,default")


if __name__ == "__main__":
    unittest.main()
