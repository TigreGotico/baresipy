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


class TestMediaEncryptionAccountLine(unittest.TestCase):
    def test_media_encryption_appended_to_account_line(self):
        bs = make_baresip(user="u", pwd="p", gateway="example.com",
                           media_encryption="srtp-mand")
        self.assertIn(";mediaenc=srtp-mand", bs._login)

    def test_no_media_encryption_omits_mediaenc(self):
        bs = make_baresip(user="u", pwd="p", gateway="example.com")
        self.assertNotIn("mediaenc", bs._login)

    def test_login_sends_account_line_with_mediaenc(self):
        bs = make_baresip(user="u", pwd="p", gateway="example.com",
                           media_encryption="dtls_srtp")
        bs.ready = True
        with patch.object(bs.baresip, "sendline") as h:
            bs.login()
        sent = h.call_args[0][0]
        self.assertIn(";mediaenc=dtls_srtp", sent)


class TestSipCafileConfig(unittest.TestCase):
    def test_sip_cafile_passed_through_to_rendered_config(self):
        bs = make_baresip(sip_cafile="/etc/ssl/ca.pem")
        self.assertIn("sip_cafile\t\t/etc/ssl/ca.pem", bs.config)

    def test_media_encryption_enables_srtp_in_config(self):
        bs = make_baresip(user="u", pwd="p", gateway="example.com",
                           media_encryption="srtp")
        self.assertIn("module\t\t\tsrtp.so", bs.config)
        self.assertNotIn("#module\t\t\tsrtp.so", bs.config)

    def test_no_media_encryption_srtp_stays_disabled(self):
        bs = make_baresip()
        self.assertIn("#module\t\t\tsrtp.so", bs.config)


if __name__ == "__main__":
    unittest.main()
