from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/render_shots.py"


def pixel(path: Path, frame: int, x: int, y: int) -> tuple[int, int, int]:
    raw = subprocess.check_output([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-vf", f"select=eq(n\\,{frame})", "-frames:v", "1",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ])
    offset = (y * 64 + x) * 3
    return tuple(raw[offset:offset + 3])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class RenderShotsTest(unittest.TestCase):
    def test_explicit_style_exact_frames_and_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            assets = project / "assets"
            assets.mkdir(parents=True)
            records = []
            for asset_id, color in (("red", "red"), ("blue", "blue")):
                path = assets / f"{asset_id}.mp4"
                create = [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"color=c={color}:s=36x36:r=12:d=2",
                ]
                if asset_id == "blue":
                    create += ["-vf", "drawbox=x=0:y=18:w=36:h=18:color=red:t=fill"]
                create += ["-an", "-c:v", "mpeg4", str(path)]
                subprocess.run(create, check=True)
                records.append({"id": asset_id, "relative_path": f"assets/{asset_id}.mp4",
                                "media_type": "video", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
            (project / "assets-manifest.json").write_text(
                json.dumps({"schema_version": 1, "assets": records}), encoding="utf-8")
            plan = root / "plan.json"
            document = {
                "schema_version": 2, "fps": "12/1", "width": 64, "height": 36,
                "default_style": {
                    "composition": {"mode": "contain", "anchor_x": 0.5, "anchor_y": 0.5,
                                    "background": "#ff00ff"},
                    "color": {"mode": "none"},
                    "transition": {"in": {"type": "cut"}, "out": {"type": "cut"}},
                },
                "shots": [
                    {"id": "first", "source_id": "red", "source_in_seconds": 0,
                     "duration_frames": 12, "section": "intro", "beat_hint": "bar 1",
                     "style": {"transition": {"in": {"type": "cut"},
                                              "out": {"type": "fade", "frames": 3,
                                                      "color": "#00ff00"}}}},
                    {"id": "second", "source_id": "blue", "source_in_seconds": 0.5,
                     "duration_frames": 12, "section": "verse", "beat_hint": "bar 2",
                     "style": {
                         "composition": {"mode": "cover", "anchor_x": 0, "anchor_y": 0},
                         "color": {"mode": "eq", "brightness": 0, "contrast": 1,
                                   "saturation": 0, "gamma": 1},
                         "transition": {"in": {"type": "fade", "frames": 3,
                                                "color": "#ffffff"},
                                        "out": {"type": "cut"}},
                     }},
                ],
            }
            plan.write_text(json.dumps(document), encoding="utf-8")
            command = [sys.executable, str(SCRIPT), "--project", str(project), "--plan", str(plan)]
            validation = subprocess.run(command + ["--validate-only"], capture_output=True, text=True)
            self.assertEqual(validation.returncode, 0, validation.stderr)
            subprocess.run(command, check=True, capture_output=True, text=True)
            panel = project / "exports/animation-panel.mp4"
            board = json.loads((project / "exports/shot-board-manifest.json").read_text())
            self.assertEqual(board["frames"], 24)
            self.assertEqual(len(list((project / "cache/shots").glob("*.mp4"))), 2)
            with (project / "exports/shot-list.csv").open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([r["start_frame"] for r in rows], ["0", "12"])

            left_bar = pixel(panel, 0, 2, 18)
            red_center = pixel(panel, 0, 32, 18)
            fade_green = pixel(panel, 11, 32, 18)
            fade_white = pixel(panel, 12, 32, 18)
            gray_center = pixel(panel, 16, 32, 18)
            self.assertGreater(left_bar[0], 150)
            self.assertGreater(left_bar[2], 150)
            self.assertGreater(red_center[0], red_center[1] + 100)
            self.assertGreater(fade_green[1], fade_green[0] + 60)
            self.assertTrue(all(channel > 180 for channel in fade_white))
            self.assertLess(max(gray_center) - min(gray_center), 15)

            keys = {item["id"]: item["cache_key"] for item in board["shots"]}
            first_clip = project / "cache/shots" / f"{keys['first']}.mp4"
            before = first_clip.stat().st_mtime_ns
            subprocess.run(command, check=True, capture_output=True, text=True)
            self.assertEqual(first_clip.stat().st_mtime_ns, before)
            first_clip.write_bytes(first_clip.read_bytes() + b"corrupted-cache-tail")
            subprocess.run(command, check=True, capture_output=True, text=True)
            self.assertNotEqual(first_clip.stat().st_mtime_ns, before)

            first_repaired = first_clip.stat().st_mtime_ns
            document["shots"][1]["style"]["color"] = {"mode": "none"}
            plan.write_text(json.dumps(document), encoding="utf-8")
            subprocess.run(command, check=True, capture_output=True, text=True)
            revised = json.loads((project / "exports/shot-board-manifest.json").read_text())
            revised_keys = {item["id"]: item["cache_key"] for item in revised["shots"]}
            self.assertEqual(revised_keys["first"], keys["first"])
            self.assertNotEqual(revised_keys["second"], keys["second"])
            self.assertEqual(first_clip.stat().st_mtime_ns, first_repaired)
            blue_center = pixel(panel, 16, 32, 18)
            self.assertGreater(blue_center[2], blue_center[0] + 80)

            document["shots"][1]["source_in_seconds"] = 1.5
            plan.write_text(json.dumps(document), encoding="utf-8")
            failed = subprocess.run(command + ["--validate-only"], capture_output=True, text=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("exceeds source duration", failed.stderr)

            document["shots"][1]["source_in_seconds"] = 0.5
            document["shots"][1]["style"]["transition"]["in"]["color"] = "black"
            plan.write_text(json.dumps(document), encoding="utf-8")
            failed_style = subprocess.run(command + ["--validate-only"], capture_output=True, text=True)
            self.assertNotEqual(failed_style.returncode, 0)
            self.assertIn("#RRGGBB", failed_style.stderr)

    def test_plan_requires_explicit_style(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            (project / "assets-manifest.json").write_text(
                json.dumps({"schema_version": 1, "assets": []}), encoding="utf-8")
            plan = root / "plan.json"
            plan.write_text(json.dumps({"schema_version": 2, "fps": "12/1",
                                        "width": 64, "height": 36, "shots": []}), encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCRIPT), "--project", str(project),
                                     "--plan", str(plan), "--validate-only"],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("default_style", result.stderr)


if __name__ == "__main__":
    unittest.main()
