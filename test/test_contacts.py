import tempfile
import unittest
from unittest.mock import patch

from baresipy.contacts import (
    ContactList,
    ContactExists,
    ContactDoesNotExist,
)


class TestContactList(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.contacts = ContactList(db_dir=self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_db_created_in_custom_dir(self):
        self.assertTrue(
            self.contacts.db_path.startswith(self.tmpdir.name))

    def test_add_and_get_contact(self):
        self.contacts.add_contact("alice", "sip:alice@example.com")
        contact = self.contacts.get_contact("alice")
        self.assertIsNotNone(contact)
        self.assertEqual(contact["url"], "sip:alice@example.com")

    def test_add_duplicate_contact_raises(self):
        self.contacts.add_contact("alice", "sip:alice@example.com")
        with self.assertRaises(ContactExists):
            self.contacts.add_contact("alice", "sip:alice2@example.com")

    def test_update_contact(self):
        self.contacts.add_contact("alice", "sip:alice@example.com")
        self.contacts.update_contact("alice", "sip:alice-new@example.com")
        contact = self.contacts.get_contact("alice")
        self.assertEqual(contact["url"], "sip:alice-new@example.com")

    def test_update_missing_contact_raises(self):
        with self.assertRaises(ContactDoesNotExist):
            self.contacts.update_contact("bob", "sip:bob@example.com")

    def test_remove_contact(self):
        self.contacts.add_contact("alice", "sip:alice@example.com")
        self.contacts.remove_contact("alice")
        self.assertIsNone(self.contacts.get_contact("alice"))

    def test_remove_missing_contact_raises(self):
        with self.assertRaises(ContactDoesNotExist):
            self.contacts.remove_contact("bob")

    def test_is_contact(self):
        self.contacts.add_contact("alice", "sip:alice@example.com")
        self.assertTrue(
            self.contacts.is_contact("sip:alice@example.com"))
        self.assertFalse(
            self.contacts.is_contact("sip:nobody@example.com"))

    def test_list_contacts(self):
        self.contacts.add_contact("alice", "sip:alice@example.com")
        self.contacts.add_contact("bob", "sip:bob@example.com")
        names = sorted(u["name"] for u in self.contacts.list_contacts())
        self.assertEqual(names, ["alice", "bob"])

    def test_import_baresip_contacts_missing_file_is_noop(self):
        with tempfile.TemporaryDirectory() as fake_home:
            with patch("baresipy.contacts.expanduser",
                       return_value=fake_home):
                # should not raise even though ~/.baresip/contacts
                # doesn't exist under fake_home
                self.contacts.import_baresip_contacts()
        self.assertEqual(self.contacts.list_contacts(), [])


if __name__ == "__main__":
    unittest.main()
