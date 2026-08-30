import tempfile
import unittest

from baresipy.config import render_config


class TestRenderConfig(unittest.TestCase):
    def test_default_uses_alsa(self):
        config = render_config()
        self.assertIn("audio_player\t\talsa,default", config)
        self.assertIn("audio_source\t\talsa,default", config)
        self.assertIn("audio_alert\t\talsa,default", config)
        self.assertIn("module\t\t\talsa.so", config)
        self.assertIn("module\t\t\tpulse.so", config)

    def test_custom_audio_driver(self):
        config = render_config(audio_driver="pulse,default")
        self.assertIn("audio_player\t\tpulse,default", config)
        self.assertIn("audio_source\t\tpulse,default", config)
        self.assertIn("audio_alert\t\tpulse,default", config)

    def test_headless_disables_real_sound_modules(self):
        config = render_config(headless=True)
        for line in config.splitlines():
            self.assertNotEqual(line.strip(), "module\t\t\talsa.so")
            self.assertNotEqual(line.strip(), "module\t\t\tpulse.so")
        self.assertIn("#module\t\t\talsa.so", config)
        self.assertIn("#module\t\t\tpulse.so", config)

    def test_headless_uses_ausine_and_aufile(self):
        config = render_config(headless=True)
        self.assertIn("audio_source\t\tausine,400", config)
        self.assertIn("audio_player\t\taufile,/dev/null", config)
        self.assertIn("audio_alert\t\taufile,/dev/null", config)
        self.assertIn("module\t\t\tausine.so", config)

    def test_audio_path_dir_substitution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = render_config(audio_path=tmpdir)
            self.assertIn("audio_path\t\t" + tmpdir, config)
            self.assertNotIn("#audio_path\t\t/usr/share/baresip", config)

    def test_audio_path_false_disables_sounds(self):
        config = render_config(audio_path=False)
        self.assertIn("audio_path\t\t/dont/load", config)

    def test_audio_path_none_leaves_default_commented(self):
        config = render_config()
        self.assertIn("#audio_path\t\t/usr/share/baresip", config)


class TestRenderConfigSndfile(unittest.TestCase):
    def test_sndfile_disabled_by_default(self):
        config = render_config()
        self.assertIn("#module\t\t\tsndfile.so", config)
        self.assertNotIn("\nmodule\t\t\tsndfile.so\n", config)
        self.assertNotIn("snd_path", config)

    def test_sndfile_enabled(self):
        config = render_config(enable_sndfile=True, snd_path="/tmp/rec")
        self.assertIn("module\t\t\tsndfile.so", config)
        self.assertNotIn("#module\t\t\tsndfile.so", config)
        self.assertIn("snd_path\t\t/tmp/rec", config)

    def test_sndfile_enabled_requires_snd_path(self):
        with self.assertRaises(ValueError):
            render_config(enable_sndfile=True)


class TestRenderConfigTlsSrtp(unittest.TestCase):
    def test_sip_cafile_none_leaves_config_unchanged(self):
        config = render_config()
        self.assertNotIn("sip_cafile", config)

    def test_sip_cafile_set(self):
        config = render_config(sip_cafile="/etc/ssl/ca.pem")
        self.assertIn("sip_cafile\t\t/etc/ssl/ca.pem", config)

    def test_srtp_disabled_by_default(self):
        config = render_config()
        self.assertIn("#module\t\t\tsrtp.so", config)

    def test_srtp_enabled(self):
        config = render_config(enable_srtp=True)
        self.assertIn("module\t\t\tsrtp.so", config)
        self.assertNotIn("#module\t\t\tsrtp.so", config)


if __name__ == "__main__":
    unittest.main()
