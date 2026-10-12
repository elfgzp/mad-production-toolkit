from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/card.py"


def alpha_sum(path: Path, second: float) -> int:
    raw = subprocess.run([
        "ffmpeg", "-v", "error", "-ss", str(second), "-i", str(path),
        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-",
    ], capture_output=True, check=True).stdout
    return sum(raw[3::4])


class CardToolTest(unittest.TestCase):
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
