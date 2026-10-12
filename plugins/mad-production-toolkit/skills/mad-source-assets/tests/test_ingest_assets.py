from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ingest_assets.py"


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class IngestAssetsTest(unittest.TestCase):
    def test_portable_manifest_and_immutable_asset_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "private-input.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=blue:s=64x36:r=12:d=1",
                "-an", "-c:v", "mpeg4", str(source),
            ], check=True)
            config = root / "asset-config.json"
            config.write_text(json.dumps({"schema_version": 1, "assets": [{
                "id": "synthetic-blue", "path": str(source), "media_type": "video",
                "origin": {"type": "label", "value": "synthetic_fixture"},
                "creator": "Example Studio", "rights_status": "owned",
            }]}), encoding="utf-8")
            project = root / "project"
            command = [sys.executable, str(SCRIPT), "--config", str(config), "--project", str(project)]
            subprocess.run(command, check=True, capture_output=True, text=True)
            manifest_path = project / "assets-manifest.json"
            raw = manifest_path.read_text(encoding="utf-8")
            self.assertNotIn(str(source), raw)
            item = json.loads(raw)["assets"][0]
            self.assertEqual(item["relative_path"], "assets/synthetic-blue.mp4")
            self.assertEqual(item["sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(item["media"]["video"]["width"], 64)
            subprocess.run(command, check=True, capture_output=True, text=True)
            source.write_bytes(source.read_bytes() + b"changed")
            failed = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("different bytes", failed.stderr)

    def test_rejects_private_origin_reference(self) -> None:
        sys.path.insert(0, str(SCRIPT.parent))
        from ingest_assets import validate_origin

        with self.assertRaises(ValueError):
            validate_origin({"type": "label", "value": "/absolute/private/path"})
        for url in (
            "https://example.org/x?token=secret",
            "https://example.org/x?X-Amz-Signature=secret&X-Amz-Credential=private",
            "https://example.org/x?X-Goog-Signature=secret",
            "https://example.org/x?utm_source=example",
            "https://example.org/x?",
            "https://example.org/x#section",
            "https://example.org/x#",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_origin({"type": "public_url", "value": url})
        public = "https://example.org/media/clip.mp4"
        self.assertEqual(
            validate_origin({"type": "public_url", "value": public}),
            {"type": "public_url", "value": public},
        )


if __name__ == "__main__":
    unittest.main()
