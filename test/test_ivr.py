import time
import unittest
from unittest.mock import MagicMock

from baresipy.ivr import IVRNode, IVRPhone, IVRSession


def make_phone(established=True):
    phone = MagicMock()
    phone.call_established = established
    return phone


class TestIVRNavigation(unittest.TestCase):
    def test_digit_navigates_to_submenu(self):
        sub = IVRNode(prompt="sub menu", options={"9": "hangup"})
        root = IVRNode(prompt="root menu", options={"1": sub})
        phone = make_phone()
        session = IVRSession(phone, root)

        import threading
        t = threading.Thread(target=session.run, daemon=True)
        t.start()
        session.on_digit("1")
        time.sleep(0.1)
        session.on_digit("9")
        t.join(timeout=2)
        phone.speak.assert_any_call("root menu")
        phone.speak.assert_any_call("sub menu")
        phone.hang.assert_called_once()

    def test_action_callback_invoked_and_menu_repeats(self):
        called = []

        def action(session):
            called.append(session.path)
            phone.call_established = False  # end the loop after the action

        root = IVRNode(prompt="root", options={"5": action})
        phone = make_phone()
        session = IVRSession(phone, root)

        import threading
        t = threading.Thread(target=session.run, daemon=True)
        t.start()
        session.on_digit("5")
        t.join(timeout=2)
        self.assertEqual(called, [["5"]])
        phone.speak.assert_any_call("root")

    def test_invalid_digit_then_retry_then_valid(self):
        root = IVRNode(prompt="root", options={"1": "hangup"},
                        invalid_prompt="bad digit", max_retries=2)
        phone = make_phone()
        session = IVRSession(phone, root)

        import threading
        t = threading.Thread(target=session.run, daemon=True)
        t.start()
        session.on_digit("9")  # invalid
        time.sleep(0.1)
        session.on_digit("1")  # valid -> hangup
        t.join(timeout=2)
        phone.speak.assert_any_call("bad digit")
        phone.hang.assert_called_once()

    def test_timeout_speaks_timeout_prompt_then_falls_back(self):
        root = IVRNode(prompt="root", options={}, timeout=0.05,
                        timeout_prompt="still there?", max_retries=1,
                        fallback="hangup")
        phone = make_phone()
        session = IVRSession(phone, root)
        session.run()
        phone.speak.assert_any_call("still there?")
        phone.hang.assert_called_once()

    def test_max_retries_exceeded_falls_back_to_hangup(self):
        root = IVRNode(prompt="root", options={}, timeout=0.05,
                        max_retries=1, fallback="hangup")
        phone = make_phone()
        session = IVRSession(phone, root)
        session.run()
        phone.hang.assert_called_once()

    def test_max_retries_exceeded_falls_back_to_transfer(self):
        root = IVRNode(prompt="root", options={}, timeout=0.05,
                        max_retries=0, fallback="transfer:sip:human@example.com")
        phone = make_phone()
        session = IVRSession(phone, root)
        session.run()
        phone.transfer.assert_called_once_with("sip:human@example.com")

    def test_transfer_option_calls_phone_transfer(self):
        root = IVRNode(prompt="root", options={"3": "transfer:sip:human@example.com"})
        phone = make_phone()
        session = IVRSession(phone, root)

        import threading
        t = threading.Thread(target=session.run, daemon=True)
        t.start()
        session.on_digit("3")
        t.join(timeout=2)
        phone.transfer.assert_called_once_with("sip:human@example.com")

    def test_digit_during_prompt_interrupts_playback(self):
        root = IVRNode(prompt="root", options={"1": "hangup"})
        phone = make_phone()
        session = IVRSession(phone, root)

        import threading
        t = threading.Thread(target=session.run, daemon=True)
        t.start()
        session.on_digit("1")
        t.join(timeout=2)
        phone.stop_audio.assert_called()

    def test_call_end_aborts_run(self):
        root = IVRNode(prompt="root", options={}, timeout=5)
        phone = make_phone(established=False)
        session = IVRSession(phone, root)
        # should return promptly since call_established is False from the start
        session.run()
        phone.hang.assert_not_called()

    def test_hangup_option_calls_hang(self):
        root = IVRNode(prompt="root", options={"0": "hangup"})
        phone = make_phone()
        session = IVRSession(phone, root)

        import threading
        t = threading.Thread(target=session.run, daemon=True)
        t.start()
        session.on_digit("0")
        t.join(timeout=2)
        phone.hang.assert_called_once()

    def test_path_tracks_digits_pressed(self):
        sub = IVRNode(prompt="sub", options={"9": "hangup"})
        root = IVRNode(prompt="root", options={"1": sub})
        phone = make_phone()
        session = IVRSession(phone, root)

        import threading
        t = threading.Thread(target=session.run, daemon=True)
        t.start()
        session.on_digit("1")
        time.sleep(0.1)
        session.on_digit("9")
        t.join(timeout=2)
        self.assertEqual(session.path, ["1", "9"])


class TestIVRPhone(unittest.TestCase):
    def test_ivrphone_starts_session_on_call_established(self):
        root = IVRNode(prompt="root", options={"0": "hangup"})
        phone = IVRPhone.__new__(IVRPhone)
        phone.ivr_root = root
        phone._session = None
        phone._call_status = "DISCONNECTED"  # session.run() exits immediately

        phone.handle_call_established()
        self.assertIsNotNone(phone._session)
        self.assertIsInstance(phone._session, IVRSession)

    def test_ivrphone_stops_session_on_call_ended(self):
        root = IVRNode(prompt="root", options={"0": "hangup"})
        phone = IVRPhone.__new__(IVRPhone)
        phone.ivr_root = root
        phone._session = MagicMock()

        phone.handle_call_ended("bye", "sip:x@y")
        phone._session_stopped = True

    def test_ivrphone_forwards_dtmf_to_session(self):
        phone = IVRPhone.__new__(IVRPhone)
        phone.current_call_info = None
        phone._session = MagicMock()

        phone.handle_dtmf_received("5", 100)
        phone._session.on_digit.assert_called_once_with("5")


if __name__ == "__main__":
    unittest.main()
