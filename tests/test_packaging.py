"""Checks for files shipped by the marketplace's installable plugin subtree."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PluginPackagingTest(unittest.TestCase):
    def test_installed_plugin_contains_complete_python_requirements(self) -> None:
        marketplace = json.loads(
            (ROOT / ".agents/plugins/marketplace.json").read_text(encoding="utf-8")
        )
        source = (ROOT / marketplace["plugins"][0]["source"]["path"]).resolve()
        self.assertTrue(source.is_relative_to(ROOT))

        with tempfile.TemporaryDirectory(prefix="mad-package-") as temporary:
            installed = Path(temporary) / "mad-production-toolkit"
            shutil.copytree(source, installed)
            requirements = installed / "requirements.txt"
            self.assertTrue(requirements.is_file(), "installed plugin lacks requirements.txt")
            self.assertEqual(
                requirements.read_text(encoding="utf-8"),
                (ROOT / "requirements.txt").read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
