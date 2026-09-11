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


class TestLoginRetryDisabledByDefault(unittest.TestCase):
    def test_default_quits_immediately(self):
        bs = make_baresip()
        with patch.object(bs, "handle_login_failure") as hf, \
                patch("baresipy.threading.Timer") as mock_timer:
            bs._handle_output_line("ua: SIP register failed: bad creds")
        hf.assert_called_once()
        mock_timer.assert_not_called()


class TestLoginRetryEnabled(unittest.TestCase):
    def setUp(self):
        self.bs = make_baresip(max_login_retries=2, login_retry_delay=1.0)

    def test_failure_schedules_retry_instead_of_quitting(self):
        with patch.object(self.bs, "handle_login_failure") as hf, \
                patch.object(self.bs, "handle_login_retry") as hr, \
                patch("baresipy.threading.Timer") as mock_timer:
            timer_instance = MagicMock()
            mock_timer.return_value = timer_instance
            self.bs._handle_output_line(
                "ua: SIP register failed: bad creds")
        hf.assert_not_called()
        hr.assert_called_once_with(1)
        mock_timer.assert_called_once_with(1.0, self.bs.login)
        timer_instance.start.assert_called_once()

    def test_exhausting_retries_eventually_calls_handle_login_failure(self):
        with patch.object(self.bs, "handle_login_failure") as hf, \
                patch("baresipy.threading.Timer"):
            for _ in range(self.bs.max_login_retries):
                self.bs._handle_output_line(
                    "ua: SIP register failed: bad creds")
            hf.assert_not_called()
            # one more failure exceeds max_login_retries
            self.bs._handle_output_line(
                "ua: SIP register failed: bad creds")
        hf.assert_called_once()

    def test_successful_login_resets_retry_counter(self):
        self.bs._login_retry_count = 2
        self.bs._handle_output_line(
            "All 1 useragent registered successfully!")
        self.assertEqual(self.bs._login_retry_count, 0)


if __name__ == "__main__":
    unittest.main()
