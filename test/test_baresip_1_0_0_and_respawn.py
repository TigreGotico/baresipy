"""Follow-ups to baresipy#21, found in review and in a live run on baresip 1.0.0.

- logout() sent /uadelall, which baresip 1.0.0 does not have ("command not
  found (uadelall)"), so after logout() and login() the registrar saw the old
  account and the new one side by side.
- Login success matched any line with "200 OK", so "REFER reply 200 OK" and
  "presence: notifier closed (200 OK)" fired handle_login_success.
- A respawned baresip kept ready and the local-account flag of the dead one, so
  the new process never got its local account.
- A baresip that exits at start respawned every 0.5 s forever.
- quit() left ready True, so do_command(), logout() and login() raised
  AttributeError on the cleared process.
"""
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import baresipy


def make_baresip(**kwargs):
    kwargs.setdefault("autostart", False)
    kwargs.setdefault("config_path", tempfile.mkdtemp())
    with patch.object(baresipy.pexpect, "spawn") as mock_spawn:
        mock_spawn.return_value = MagicMock()
        bs = baresipy.BareSIP(**kwargs)
    return bs


class TestLogoutOnBaresip100(unittest.TestCase):
    def test_logout_sends_uadelall(self):
        bs = make_baresip(user="alice", pwd="secret", gateway="host")
        bs.logout()
        bs.baresip.sendline.assert_called_with("/uadelall")

    def test_unknown_uadelall_falls_back_to_uadel_for_the_own_account(self):
        bs = make_baresip(user="alice", pwd="secret", gateway="host")
        bs._handle_output_line("command not found (uadelall)")
        bs.baresip.sendline.assert_called_with("/uadel sip:alice@host")

    def test_fallback_in_registrar_less_mode_uses_the_local_account(self):
        bs = make_baresip(user="bob")
        bs._handle_output_line("command not found (uadelall)")
        bs.baresip.sendline.assert_called_with("/uadel sip:bob@0.0.0.0")


class TestLoginSuccessMatchesTheRegistrationLine(unittest.TestCase):
    def setUp(self):
        self.bs = make_baresip(user="alice", pwd="secret", gateway="host")

    def _fires(self, line):
        with patch.object(self.bs, "handle_login_success") as ok:
            self.bs._handle_output_line(line)
        return ok.called

    def test_baresip_1_0_0_registration_line(self):
        self.assertTrue(self._fires("sip:alice@host: {0/UDP/v4} 200 OK (baresip) [1 binding]"))

    def test_current_baresip_registration_line(self):
        self.assertTrue(self._fires(
            "sip:alice@host: (prio 0) {0/UDP/v4} 200 OK (Asterisk) [2 bindings]"))

    def test_other_2xx_registration_codes_count(self):
        self.assertTrue(self._fires("sip:alice@host: {1/TCP/v6} 202 Accepted (reg) [1 binding]"))

    def test_a_refer_reply_is_not_a_login(self):
        self.assertFalse(self._fires("sip:bob@example.com: REFER reply 200 OK"))

    def test_a_presence_notifier_line_is_not_a_login(self):
        self.assertFalse(self._fires("presence: notifier closed (200 OK)"))


class TestRespawnStartsClean(unittest.TestCase):
    def test_a_new_process_resets_ready_and_the_local_account_flag(self):
        bs = make_baresip(user="bob")
        bs.ready = True
        bs._local_ua_added = True
        bs.current_call = "sip:x@y"
        bs._call_status = "ESTABLISHED"
        bs._prev_output = "old line"
        with patch.object(baresipy.pexpect, "spawn", return_value=MagicMock()):
            bs.startBareSIPSubProcess()
        self.assertFalse(bs.ready)
        self.assertFalse(bs._local_ua_added)
        self.assertIsNone(bs.current_call)
        self.assertIsNone(bs._call_status)
        self.assertEqual(bs._prev_output, "")
        # the new process gets its local account again
        bs._handle_output_line("baresip is ready.")
        bs.baresip.sendline.assert_called_with("/uanew sip:bob@0.0.0.0;regint=0")


class TestRespawnBackoff(unittest.TestCase):
    def test_a_baresip_that_keeps_exiting_backs_off_and_stops(self):
        bs = make_baresip(user="bob")
        dead = MagicMock()
        dead.isalive.return_value = False
        delays = []
        with patch.object(baresipy.pexpect, "spawn", return_value=dead), \
                patch.object(baresipy, "sleep", side_effect=delays.append), \
                patch.object(bs, "quit"):
            bs.baresip = dead
            bs.run()
        self.assertFalse(bs.running)
        self.assertEqual(len(delays), bs.max_respawns)
        self.assertEqual(delays, sorted(delays))
        self.assertGreater(delays[-1], delays[0])

    def test_reaching_ready_alone_does_not_reset_the_respawn_count(self):
        bs = make_baresip(user="bob")
        bs._respawn_count = 3
        bs._handle_output_line("baresip is ready.")
        self.assertEqual(bs._respawn_count, 3)


def ready_then_dead(*args, **kwargs):
    """A baresip that prints "baresip is ready." once, then exits."""
    proc = MagicMock()
    checks = {"n": 0}

    def isalive():
        checks["n"] += 1
        return checks["n"] <= 1

    proc.isalive.side_effect = isalive
    proc.readline.return_value = b"baresip is ready.\n"
    return proc


class TestRespawnAfterReady(unittest.TestCase):
    """A baresip that dies right after ready must not respawn forever."""

    def test_a_baresip_that_dies_after_ready_still_gives_up(self):
        bs = make_baresip(user="bob")
        delays = []

        def fake_sleep(seconds):
            delays.append(seconds)
            if len(delays) > 50:
                bs.running = False
                raise AssertionError("respawned more than 50 times")

        with patch.object(baresipy.pexpect, "spawn", side_effect=ready_then_dead), \
                patch.object(baresipy, "sleep", side_effect=fake_sleep), \
                patch("baresipy.monotonic", create=True, return_value=100.0), \
                patch.object(bs, "quit"):
            bs.baresip = ready_then_dead()
            try:
                bs.run()
            except AssertionError:
                pass
        self.assertFalse(bs.running)
        self.assertEqual(len(delays), bs.max_respawns)

    def test_a_sustained_ready_period_resets_the_respawn_count(self):
        bs = make_baresip(user="bob")
        bs._respawn_count = 3
        clock = iter([0.0, bs.respawn_reset_after + 1.0])

        def stop(seconds):
            bs.running = False

        with patch.object(baresipy.pexpect, "spawn", side_effect=ready_then_dead), \
                patch.object(baresipy, "sleep", side_effect=stop), \
                patch("baresipy.monotonic", create=True, side_effect=lambda: next(clock)), \
                patch.object(bs, "quit"):
            bs.baresip = ready_then_dead()
            bs.run()
        # reset by the long ready period, then counted once for this exit
        self.assertEqual(bs._respawn_count, 1)


class TestCallsAfterQuit(unittest.TestCase):
    def setUp(self):
        self.bs = make_baresip(user="alice", pwd="secret", gateway="host")
        self.bs.ready = True
        self.bs.running = True
        self.bs.quit()

    def test_quit_clears_ready(self):
        self.assertFalse(self.bs.ready)

    def test_do_command_after_quit_does_not_raise(self):
        self.bs.do_command("/dial sip:x@y")

    def test_logout_after_quit_does_not_raise(self):
        self.bs.logout()

    def test_login_after_quit_does_not_raise(self):
        self.bs.login()


if __name__ == "__main__":
    unittest.main()
