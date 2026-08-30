import unittest


class TestOvosOptionalDependency(unittest.TestCase):
    def test_baresipy_import_does_not_require_ovos(self):
        import baresipy  # noqa: F401
        self.assertTrue(hasattr(baresipy, "BareSIP"))

    def test_baresipy_ovos_import_error_mentions_extra(self):
        try:
            import ovos_plugin_manager  # noqa: F401
        except ImportError:
            pass
        else:
            self.skipTest("ovos-plugin-manager is installed in this env")

        with self.assertRaises(ImportError) as ctx:
            import baresipy.ovos  # noqa: F401
        self.assertIn("baresipy[ovos]", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
