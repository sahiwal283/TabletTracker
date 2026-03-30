"""version_display reads __version__.py from disk."""
import unittest

from app.utils.version_display import read_version_constants, _version_py_path


class TestVersionDisplay(unittest.TestCase):
    def test_reads_project_version_file(self):
        self.assertTrue(_version_py_path().name == "__version__.py")
        meta = read_version_constants()
        self.assertIn("__version__", meta)
        self.assertRegex(meta["__version__"], r"^\d+\.\d+\.\d+")
        self.assertEqual(meta["__title__"], "TabletTracker")
        self.assertTrue(len(meta["__description__"]) > 10)


if __name__ == "__main__":
    unittest.main()
