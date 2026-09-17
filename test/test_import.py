import unittest


class TestImport(unittest.TestCase):
    def test_import_baresipy(self):
        import baresipy
        self.assertTrue(hasattr(baresipy, "BareSIP"))

    def test_import_contacts(self):
        from baresipy.contacts import ContactList
        self.assertTrue(callable(ContactList))


if __name__ == "__main__":
    unittest.main()
