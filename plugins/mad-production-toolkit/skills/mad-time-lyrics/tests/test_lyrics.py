from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/lyrics.py"


class LyricsToolTest(unittest.TestCase):
    def test_export_and_alpha_render(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cues = root / "cues.json"
            cues.write_text(json.dumps({
                "duration_seconds": 2.0,
                "cues": [{"start": 0.4, "end": 1.4,
                          "original": "Signal", "translation": "Response"}],
            }), encoding="utf-8")
            subprocess.run([sys.executable, str(SCRIPT), "export", "--cues", str(cues),
                            "--output-dir", str(root / "subs")], check=True, capture_output=True)
            srt = (root / "subs/lyrics.srt").read_text(encoding="utf-8")
            self.assertIn("00:00:00,400 --> 00:00:01,400", srt)
            self.assertIn("Response", srt)
            overlay = root / "lyrics.mov"
            style = ROOT / "examples/style.json"
            subprocess.run([sys.executable, str(SCRIPT), "render", "--cues", str(cues),
                            "--style", str(style), "--output", str(overlay)],
                           check=True, capture_output=True)
            probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                    "-show_entries", "stream=nb_frames,pix_fmt", "-of", "json",
                                    str(overlay)], check=True, capture_output=True, text=True)
            stream = json.loads(probe.stdout)["streams"][0]
            self.assertEqual(int(stream["nb_frames"]), round(2 * 30000 / 1001))
            self.assertIn("yuva", stream["pix_fmt"])
            for at, expect_visible in (("0.0", False), ("1.0", True)):
                image = subprocess.run(["ffmpeg", "-v", "error", "-ss", at, "-i", str(overlay),
                                        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-"],
                                       check=True, capture_output=True).stdout
                alpha = image[3::4]
                self.assertEqual(len(alpha), 640 * 360)
                self.assertEqual(any(alpha), expect_visible)

    def test_rejects_missing_or_overlapping_cues(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cues = Path(temporary) / "bad.json"
            cues.write_text(json.dumps({"duration_seconds": 2.0, "cues": [
                {"start": 0.2, "end": 1.2, "original": "A"},
                {"start": 1.1, "end": 1.8, "original": "B"},
            ]}), encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCRIPT), "validate", "--cues", str(cues)],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("overlap", result.stderr)

    def test_second_visual_style_relative_font_and_24_fps(self) -> None:
        candidates = (
            Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        )
        font = next((path for path in candidates if path.is_file()), None)
        if font is None:
            self.skipTest("No test font available")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            styles = root / "styles"
            (styles / "fonts").mkdir(parents=True)
            shutil.copyfile(font, styles / "fonts/demo.ttf")
            style = json.loads((ROOT / "examples/style-alt.json").read_text(encoding="utf-8"))
            style["original_font"] = "fonts/demo.ttf"
            style["translation_font"] = "fonts/demo.ttf"
            style_path = styles / "style.json"
            style_path.write_text(json.dumps(style), encoding="utf-8")
            cues = root / "cues.json"
            cues.write_text(json.dumps({"duration_seconds": 2.0,
                                        "cues": [{"start": 0.4, "end": 1.4,
                                                  "original": "Signal", "translation": "Response"}]}),
                            encoding="utf-8")
            elsewhere = root / "different-working-directory"
            elsewhere.mkdir()
            overlay = root / "alt.mov"
            render = subprocess.run([
                sys.executable, str(SCRIPT), "render", "--cues", str(cues),
                "--style", str(style_path), "--output", str(overlay),
            ], cwd=elsewhere, capture_output=True, text=True)
            self.assertEqual(render.returncode, 0, render.stderr)
            metadata = subprocess.run([
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=nb_frames,avg_frame_rate,pix_fmt",
                "-of", "json", str(overlay),
            ], capture_output=True, text=True, check=True)
            stream = json.loads(metadata.stdout)["streams"][0]
            self.assertEqual(int(stream["nb_frames"]), 48)
            self.assertEqual(stream["avg_frame_rate"], "24/1")
            self.assertIn("yuva", stream["pix_fmt"])

    def test_motion_modes_and_directions_change_visible_frames(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        from lyrics import Cue, make_artwork, render_frame

        original = json.loads((ROOT / "examples/style.json").read_text(encoding="utf-8"))
        cue = Cue(0.4, 1.4, "Signal", "Response")
        artwork = make_artwork(cue, original)
        forward = render_frame(artwork, 0.7, original)
        reversed_style = json.loads(json.dumps(original))
        reversed_style["highlight"]["direction"] = "right-to-left"
        self.assertNotEqual(forward, render_frame(artwork, 0.7, reversed_style))
        faster_style = json.loads(json.dumps(original))
        faster_style["highlight"]["duration_seconds"] = 0.2
        self.assertNotEqual(forward, render_frame(artwork, 0.7, faster_style))
        linear_style = json.loads(json.dumps(original))
        linear_style["highlight"]["easing"] = "linear"
        self.assertNotEqual(forward, render_frame(artwork, 0.7, linear_style))
        down_style = json.loads(json.dumps(original))
        down_style["entrance"]["direction"] = "down"
        self.assertNotEqual(render_frame(artwork, 0.45, original),
                            render_frame(artwork, 0.45, down_style))
        fade_style = json.loads(json.dumps(original))
        fade_style["entrance"]["mode"] = "fade"
        self.assertNotEqual(render_frame(artwork, 0.45, original),
                            render_frame(artwork, 0.45, fade_style))
        slide_exit_style = json.loads(json.dumps(original))
        slide_exit_style["exit"]["mode"] = "slide"
        slide_exit_style["exit"]["distance_pixels"] = 30
        self.assertNotEqual(render_frame(artwork, 1.35, original),
                            render_frame(artwork, 1.35, slide_exit_style))
        alternate = json.loads((ROOT / "examples/style-alt.json").read_text(encoding="utf-8"))
        self.assertNotEqual(original["highlight"]["mode"], alternate["highlight"]["mode"])
        self.assertNotEqual(original["entrance"]["mode"], alternate["entrance"]["mode"])


if __name__ == "__main__":
    unittest.main()
