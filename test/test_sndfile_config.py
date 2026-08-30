import unittest
from unittest.mock import patch

from baresipy.config import DEFAULT, ensure_sndfile_recording, render_config


class TestEnsureSndfileRecordingWhitespaceTolerance(unittest.TestCase):
    def test_spaces_config_without_vumeter_enables_sndfile(self):
        # a user-supplied (BYO) config using spaces instead of tabs, and
        # with no vumeter.so line at all - not byte-identical to DEFAULT
        byo_config = (
            "# minimal user config\n"
            "module_path /usr/lib/baresip/modules\n"
            "\n"
            "module stdio.so\n"
            "module opus.so\n"
            "#module sndfile.so\n"
            "module alsa.so\n"
        )

        result = ensure_sndfile_recording(byo_config, "/tmp/rec")

        enabled = False
        for line in result.splitlines():
            stripped = line.strip()
            if stripped == "module sndfile.so" or \
                    (stripped.startswith("module") and
                     stripped.endswith("sndfile.so") and
                     not stripped.startswith("#")):
                enabled = True
        self.assertTrue(
            enabled,
            "sndfile.so module line should be uncommented/present and "
            "active even though the config used spaces, not tabs, and "
            "had no vumeter.so line: %r" % result)
        self.assertIn("snd_path", result)

    def test_no_modules_section_adds_module_or_warns(self):
        # a config with no "module ..." lines at all
        byo_config = (
            "# a config with no modules section whatsoever\n"
            "sip_trans_bsize 128\n"
            "call_max_calls 4\n"
        )

        sndfile_present = False
        # baresipy's LOG helper does not propagate to the root logger
        # (propagate=False), so assertLogs can't observe it directly;
        # patch LOG.warning to detect the call instead.
        with patch("baresipy.config.LOG.warning") as mock_warning:
            result = ensure_sndfile_recording(byo_config, "/tmp/rec")
            for line in result.splitlines():
                stripped = line.strip()
                if "sndfile.so" in stripped and not stripped.startswith("#"):
                    sndfile_present = True

        warned = mock_warning.called
        self.assertTrue(
            sndfile_present or warned,
            "either sndfile.so should have been added, or a warning "
            "should have been logged naming the failure")

    def test_default_template_still_enables_sndfile_regression(self):
        result = ensure_sndfile_recording(DEFAULT, "/tmp/rec")
        self.assertIn("module\t\t\tsndfile.so", result)
        self.assertNotIn("#module\t\t\tsndfile.so", result)
        self.assertIn("snd_path\t\t/tmp/rec", result)

    def test_render_config_default_template_regression(self):
        config = render_config(enable_sndfile=True, snd_path="/tmp/rec")
        self.assertIn("module\t\t\tsndfile.so", config)
        self.assertNotIn("#module\t\t\tsndfile.so", config)


if __name__ == "__main__":
    unittest.main()
