"""The release archive must stay small and contain only installation files."""

from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))

import bundle


class BundleTests(unittest.TestCase):
    def test_archive_has_sources_but_no_docs_media_or_tests(self):
        with tempfile.TemporaryDirectory() as directory:
            output = bundle.build(Path(directory) / "CornerNote.zip")
            with ZipFile(output) as archive:
                names = archive.namelist()
        self.assertIn("CornerNote/install.sh", names)
        self.assertIn("CornerNote/src/main.py", names)
        for name in names:
            self.assertFalse(name.startswith(("CornerNote/docs/", "CornerNote/tests/")), name)
            self.assertNotIn(Path(name).suffix.lower(), bundle.EXCLUDE_SUFFIXES, name)
            self.assertNotIn("__pycache__", name)


if __name__ == "__main__":
    unittest.main()
