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


class TestLoginAOR(unittest.TestCase):
    """The SIP URI and its `transport` URI parameter must be bracketed;
    `auth_pass`, `login_options` and `mediaenc` are account parameters and
    must come after the closing `>` (baresip accounts syntax)."""

    def test_default_login_is_bracketed(self):
        bs = make_baresip(user="alice", pwd="secret", gateway="host")
        self.assertEqual(
            bs._login,
            "<sip:alice@host;transport=udp>;auth_pass=secret")

    def test_transport_tls(self):
        bs = make_baresip(user="alice", pwd="secret", gateway="host",
                           transport="tls")
        self.assertEqual(
            bs._login,
            "<sip:alice@host;transport=tls>;auth_pass=secret")

    def test_login_options_after_bracket(self):
        bs = make_baresip(user="alice", pwd="secret", gateway="host",
                           login_options="answermode=auto")
        self.assertEqual(
            bs._login,
            "<sip:alice@host;transport=udp>;auth_pass=secret;"
            "answermode=auto")

    def test_media_encryption_after_bracket(self):
        bs = make_baresip(user="alice", pwd="secret", gateway="host",
                           media_encryption="srtp")
        self.assertEqual(
            bs._login,
            "<sip:alice@host;transport=udp>;auth_pass=secret;"
            "mediaenc=srtp")

    def test_options_and_mediaenc_order(self):
        bs = make_baresip(user="alice", pwd="secret", gateway="host",
                           login_options="answermode=auto",
                           media_encryption="srtp")
        self.assertEqual(
            bs._login,
            "<sip:alice@host;transport=udp>;auth_pass=secret;"
            "answermode=auto;mediaenc=srtp")

    def test_account_params_come_after_closing_bracket(self):
        bs = make_baresip(user="alice", pwd="secret", gateway="host",
                           transport="tls")
        uri_part, _, account_part = bs._login.partition(">")
        self.assertTrue(uri_part.startswith("<sip:alice@host"))
        self.assertIn("transport=tls", uri_part)
        self.assertNotIn("auth_pass", uri_part)
        self.assertEqual(account_part, ";auth_pass=secret")


if __name__ == "__main__":
    unittest.main()
