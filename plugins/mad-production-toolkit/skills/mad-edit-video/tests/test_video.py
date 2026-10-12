from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/video.py"


def invoke(*args: str) -> str:
    result = subprocess.run([sys.executable, str(SCRIPT), *args],
                            check=True, capture_output=True, text=True)
    return result.stdout


def video_hash(path: Path) -> str:
    data = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path),
                           "-map", "0:v:0", "-c", "copy", "-f", "h264", "-"],
                          check=True, capture_output=True).stdout
    return hashlib.sha256(data).hexdigest()


def blue_at(path: Path, second: float, x: int, y: int) -> int:
    frame = subprocess.run([
        "ffmpeg", "-v", "error", "-ss", str(second), "-i", str(path),
        "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-",
    ], check=True, capture_output=True).stdout
    return Image.open(io.BytesIO(frame)).convert("RGB").getpixel((x, y))[2]


class VideoToolTest(unittest.TestCase):
    def test_base_cache_overlay_and_remux(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            colors = ("red", "green", "blue", "yellow")
            panels = []
            for index, color in enumerate(colors):
                source = root / f"{color}.mp4"
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                                f"color=c={color}:s=160x90:r=30:d=2",
                                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)],
                               check=True, capture_output=True)
                panels.append({"path": source.name, "x": index % 2 * 160,
                               "y": index // 2 * 90, "width": 160, "height": 90,
                               "trim_start": 0})
            panels[0]["start_seconds"] = 0.5
            panels[0]["end_seconds"] = 1.5
            config = root / "base.json"
            config.write_text(json.dumps({"canvas": [320, 180], "fps": "30/1",
                                          "duration_seconds": 2, "background_color": "#132332",
                                          "panels": panels}), encoding="utf-8")
            base = root / "base.mp4"
            invoke("base", "--config", str(config), "--output", str(base))
            self.assertIn("cache hit", invoke("base", "--config", str(config), "--output", str(base)))
            probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                    "-show_entries", "stream=nb_frames", "-of", "json", str(base)],
                                   check=True, capture_output=True, text=True)
            self.assertEqual(int(json.loads(probe.stdout)["streams"][0]["nb_frames"]), 60)
            self.assertGreater(blue_at(base, 0, 80, 45), 30)
            self.assertLess(blue_at(base, 0.8, 80, 45), 20)
            self.assertGreater(blue_at(base, 1.8, 80, 45), 30)

            good_video = base.read_bytes()
            cache = base.with_suffix(base.suffix + ".cache.json")
            good_cache = cache.read_bytes()
            base.write_bytes(b"corrupted cache artifact")
            stale = subprocess.run([sys.executable, str(SCRIPT), "base", "--config",
                                    str(config), "--output", str(base)],
                                   capture_output=True, text=True)
            self.assertNotEqual(stale.returncode, 0, "corrupted output must not be a cache hit")
            invoke("base", "--config", str(config), "--output", str(base), "--force")
            self.assertEqual(base.read_bytes(), good_video)
            self.assertEqual(cache.read_bytes(), good_cache)
            invalid = json.loads(config.read_text(encoding="utf-8"))
            invalid["panels"][0]["crop"] = [400, 400, 0, 0]
            config.write_text(json.dumps(invalid), encoding="utf-8")
            failed = subprocess.run([sys.executable, str(SCRIPT), "base", "--config",
                                     str(config), "--output", str(base), "--force"],
                                    capture_output=True, text=True)
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(base.read_bytes(), good_video)
            self.assertEqual(cache.read_bytes(), good_cache)

            badge = root / "badge.png"
            Image.new("RGBA", (16, 16), (255, 0, 255, 255)).save(badge)
            overlay_config = root / "overlay.json"
            overlay_config.write_text(json.dumps({"base": base.name,
                                                  "layers": [{"path": badge.name, "x": 8, "y": 8,
                                                              "width": 24, "height": 24,
                                                              "start_seconds": 0.2,
                                                              "end_seconds": 1.2,
                                                              "opacity": 0.7}]}),
                                      encoding="utf-8")
            layered = root / "layered.mp4"
            invoke("overlay", "--config", str(overlay_config), "--output", str(layered))
            self.assertNotEqual(video_hash(base), video_hash(layered))
            self.assertLess(blue_at(layered, 0, 15, 15), 80)
            self.assertGreater(blue_at(layered, 0.5, 15, 15), 100)
            self.assertLess(blue_at(layered, 1.5, 15, 15), 80)

            sound = root / "sound.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                            "sine=frequency=220:sample_rate=48000:duration=2", str(sound)],
                           check=True, capture_output=True)
            remuxed = root / "with-audio.mp4"
            invoke("remux", "--video", str(layered), "--audio", str(sound),
                   "--output", str(remuxed))
            self.assertEqual(video_hash(layered), video_hash(remuxed))
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(remuxed), "-f", "null", "-"],
                           check=True, capture_output=True)
            invalid_audio = root / "invalid-audio.wav"
            invalid_audio.write_bytes(b"not an audio stream")
            for args, destination in (
                (("overlay", "--config", str(overlay_config), "--audio", str(invalid_audio),
                  "--output", str(layered), "--force"), layered),
                (("remux", "--video", str(layered), "--audio", str(invalid_audio),
                  "--output", str(remuxed), "--force"), remuxed),
            ):
                previous = destination.read_bytes()
                failed = subprocess.run([sys.executable, str(SCRIPT), *args],
                                        capture_output=True, text=True)
                self.assertNotEqual(failed.returncode, 0)
                self.assertEqual(destination.read_bytes(), previous)


if __name__ == "__main__":
    unittest.main()
