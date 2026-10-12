from __future__ import annotations

import json
import hashlib
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/card.py"


def alpha_sum(path: Path, second: float) -> int:
    raw = subprocess.run([
        "ffmpeg", "-v", "error", "-ss", str(second), "-i", str(path),
        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-",
    ], capture_output=True, check=True).stdout
    return sum(raw[3::4])


class CardToolTest(unittest.TestCase):
    def test_card_cannot_replace_an_image_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            logo = root / "logo.png"
            Image.new("RGBA", (32, 32), (30, 80, 160, 255)).save(logo)
            before = hashlib.sha256(logo.read_bytes()).hexdigest()
            config = root / "card.json"
            config.write_text(json.dumps({
                "canvas": [80, 80], "background": "solid", "color": "#101010",
                "min_gap": 0,
                "elements": [{"type": "image", "path": logo.name, "x": 40, "y": 40}],
            }), encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCRIPT), "--config", str(config),
                                     "--output", str(logo), "--force"],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(hashlib.sha256(logo.read_bytes()).hexdigest(), before)

    def test_failed_forced_render_preserves_existing_card(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "card.json"
            config.write_text(json.dumps({
                "canvas": [320, 180], "fps": "4/1", "duration_seconds": 1,
                "background": "solid", "color": "#101010", "min_gap": 0,
                "fade_in_seconds": 0, "fade_out_seconds": 0,
                "fade_easing": "linear", "fade_color": "#101010",
                "elements": [{"type": "text", "text": "TITLE", "x": 160,
                              "y": 90, "size": 24, "color": "#ffffff",
                              "motion": {"offset_from": [0, 0], "offset_to": [500, 0]}}],
            }), encoding="utf-8")
            output = root / "card.mp4"
            original = b"previous valid card"
            output.write_bytes(original)
            result = subprocess.run([sys.executable, str(SCRIPT), "--config", str(config),
                                     "--output", str(output), "--force"],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(output.exists(), "failed rerender must keep the previous card")
            self.assertEqual(output.read_bytes(), original)

    def test_alpha_title_and_opaque_outro(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            title_config = root / "title.json"
            title_config.write_text(json.dumps({
                "canvas": [320, 180], "fps": "30/1", "duration_seconds": 1,
                "background": "transparent", "fade_in_seconds": 0.1,
                "fade_out_seconds": 0.1, "fade_easing": "linear", "min_gap": 12,
                "elements": [{"type": "text", "text": "DEMO COVER", "x": 160,
                              "y": 90, "size": 28, "color": "#fff9f6",
                              "motion": {"start_seconds": 0.1, "end_seconds": 0.9,
                                         "fade_in_seconds": 0.1,
                                         "offset_from": [0, 4], "offset_to": [0, 0],
                                         "scale_from": 0.95, "scale_to": 1.0,
                                         "opacity": 0.8, "easing": "smoothstep"}}],
            }), encoding="utf-8")
            title = root / "title.mov"
            subprocess.run([sys.executable, str(SCRIPT), "--config", str(title_config),
                            "--output", str(title)], check=True, capture_output=True)
            current_umask = os.umask(0)
            os.umask(current_umask)
            self.assertEqual(stat.S_IMODE(title.stat().st_mode), 0o666 & ~current_umask)
            title.chmod(0o640)
            subprocess.run([sys.executable, str(SCRIPT), "--config", str(title_config),
                            "--output", str(title), "--force"], check=True, capture_output=True)
            self.assertEqual(stat.S_IMODE(title.stat().st_mode), 0o640)
            probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                    "-show_entries", "stream=pix_fmt,nb_frames", "-of", "json",
                                    str(title)], capture_output=True, text=True, check=True)
            stream = json.loads(probe.stdout)["streams"][0]
            self.assertIn("yuva", stream["pix_fmt"])
            self.assertEqual(int(stream["nb_frames"]), 30)
            self.assertEqual(alpha_sum(title, 0), 0)
            self.assertGreater(alpha_sum(title, 0.5), 10000)
            self.assertEqual(alpha_sum(title, 0.95), 0)

            outro_config = root / "outro.json"
            outro_config.write_text(json.dumps({
                "canvas": [320, 180], "fps": "30/1", "duration_seconds": 1,
                "background": "gradient", "top_color": "#10101f",
                "bottom_color": "#27142d", "fade_in_seconds": 0.1,
                "fade_out_seconds": 0.1, "fade_easing": "smoothstep",
                "fade_color": "#27142d", "min_gap": 12, "elements": [
                    {"type": "text", "text": "Thanks", "x": 160, "y": 90,
                     "size": 30, "color": "#fff9f6"}
                ],
            }), encoding="utf-8")
            outro = root / "outro.mp4"
            subprocess.run([sys.executable, str(SCRIPT), "--config", str(outro_config),
                            "--output", str(outro)], check=True, capture_output=True)
            self.assertEqual(stat.S_IMODE(outro.stat().st_mode), 0o666 & ~current_umask)
            png = root / "outro.png"
            subprocess.run([sys.executable, str(SCRIPT), "--config", str(outro_config),
                            "--output", str(png)], check=True, capture_output=True)
            self.assertEqual(stat.S_IMODE(png.stat().st_mode), 0o666 & ~current_umask)
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(outro), "-f", "null", "-"],
                           check=True, capture_output=True)

    def test_rejects_overlapping_title_elements(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "bad.json"
            config.write_text(json.dumps({"canvas": [320, 180], "background": "transparent",
                                          "min_gap": 12, "elements": [
                {"type": "text", "text": "TITLE", "x": 160, "y": 90,
                 "size": 30, "color": "#fff9f6"},
                {"type": "text", "text": "TOO CLOSE", "x": 160, "y": 92,
                 "size": 20, "color": "#fff9f6"},
            ]}), encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCRIPT), "--config", str(config),
                                     "--output", str(root / "bad.png")], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("overlaps", result.stderr)


if __name__ == "__main__":
    unittest.main()
