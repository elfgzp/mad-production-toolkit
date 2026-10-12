from __future__ import annotations

from array import array
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/deliver.py"


def call(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class DeliveryTest(unittest.TestCase):
    def test_outro_qa_bundle_and_zip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            song, card, mix = root / "song.mp4", root / "card.mp4", root / "mix.flac"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=red:s=64x36:r=12:d=1",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
                "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", str(song),
            ], check=True)
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=blue:s=64x36:r=24:d=0.5",
                "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(card),
            ], check=True)
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
                "-c:a", "flac", str(mix),
            ], check=True)
            final = root / "final.mp4"
            result = call("append-outro", "--song-video", str(song), "--outro-video", str(card),
                          "--mix-audio", str(mix), "--output", str(final))
            self.assertEqual(result.returncode, 0, result.stderr)
            report = root / "qa.json"
            result = call("qa", "--video", str(final), "--expect-frames", "18",
                          "--expect-duration", "1.5", "--duration-tolerance", "0.1",
                          "--report", str(report))
            self.assertEqual(result.returncode, 0, result.stderr)
            qa = json.loads(report.read_text())
            self.assertEqual(qa["frames"], 18)
            self.assertEqual(qa["full_decode"], "passed")
            self.assertIn("true_peak_dbtp", qa["loudness"])
            self.assertNotIn(str(root), report.read_text())
            tail = subprocess.check_output([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", "1.2",
                "-i", str(final), "-t", "0.2", "-vn", "-ac", "1",
                "-ar", "48000", "-f", "f32le", "pipe:1",
            ])
            samples = array("f")
            samples.frombytes(tail)
            self.assertTrue(samples)
            self.assertLess(max(abs(value) for value in samples), 0.001)

            config = root / "bundle.json"
            config.write_text(json.dumps({"schema_version": 1, "assets": [
                {"source": str(final), "destination": "exports/final.mp4",
                 "rights_status": "owned", "permission_ref": "synthetic-demo"},
                {"source": str(mix), "destination": "exports/mix.flac",
                 "rights_status": "owned", "permission_ref": "synthetic-demo"},
            ]}), encoding="utf-8")
            bundle = root / "bundle-out"
            result = call("bundle", "--config", str(config), "--output-dir", str(bundle))
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest_text = (bundle / "manifest.json").read_text()
            self.assertNotIn(str(root), manifest_text)
            manifest = json.loads(manifest_text)
            self.assertEqual([r["relative_path"] for r in manifest["assets"]],
                             ["exports/final.mp4", "exports/mix.flac"])
            self.assertEqual(manifest["assets"][0]["sha256"], hashlib.sha256(final.read_bytes()).hexdigest())
            zip_path = root / "delivery.zip"
            result = call("zip", "--video", str(final), "--audio", str(mix),
                          "--output", str(zip_path))
            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(zip_path) as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(archive.namelist(), ["final.mp4", "mix.flac"])
                self.assertEqual(hashlib.sha256(archive.read("final.mp4")).digest(),
                                 hashlib.sha256(final.read_bytes()).digest())
                self.assertEqual(hashlib.sha256(archive.read("mix.flac")).digest(),
                                 hashlib.sha256(mix.read_bytes()).digest())

    def test_short_mix_and_short_audio_fail_before_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            song, card, short_mix = root / "song.mp4", root / "card.mp4", root / "short.flac"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=red:s=64x36:r=12:d=1",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=0.5",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(song),
            ], check=True)
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=blue:s=64x36:r=12:d=0.5",
                "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(card),
            ], check=True)
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=0.8",
                "-c:a", "flac", str(short_mix),
            ], check=True)
            final = root / "final.mp4"
            result = call("append-outro", "--song-video", str(song), "--outro-video", str(card),
                          "--mix-audio", str(short_mix), "--output", str(final))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("shorter", result.stderr)
            self.assertFalse(final.exists())
            result = call("qa", "--video", str(song), "--expect-frames", "12",
                          "--expect-duration", "1", "--duration-tolerance", "0.01")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("audio/video", result.stderr)

    def test_qa_rejects_multiple_audio_streams(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "two-audio.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=red:s=64x36:r=12:d=1",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
                "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=1",
                "-map", "0:v:0", "-map", "1:a:0", "-map", "2:a:0",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
            ], check=True)
            result = call("qa", "--video", str(path), "--expect-frames", "12")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("one audio", result.stderr)

    def test_extra_mix_samples_are_cut_before_outro(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            song, card, mix = root / "song.mp4", root / "card.mp4", root / "long.flac"
            for path, color, duration in ((song, "red", "1"), (card, "blue", "0.5")):
                subprocess.run([
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"color=c={color}:s=64x36:r=12:d={duration}",
                    "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
                ], check=True)
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1.2",
                "-c:a", "flac", str(mix),
            ], check=True)
            final = root / "final.mp4"
            result = call("append-outro", "--song-video", str(song), "--outro-video", str(card),
                          "--mix-audio", str(mix), "--mix-tolerance", "0.25", "--output", str(final))
            self.assertEqual(result.returncode, 0, result.stderr)
            tail = subprocess.check_output([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", "1.1",
                "-i", str(final), "-t", "0.1", "-vn", "-ac", "1",
                "-ar", "48000", "-f", "f32le", "pipe:1",
            ])
            samples = array("f")
            samples.frombytes(tail)
            self.assertTrue(samples)
            self.assertLess(max(abs(value) for value in samples), 0.001)

    def test_append_rejects_variable_frame_rate_song(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            song, card, mix = root / "vfr.mp4", root / "card.mp4", root / "mix.flac"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=red:s=64x36:r=12:d=0.5",
                "-f", "lavfi", "-i", "color=c=blue:s=64x36:r=24:d=0.5",
                "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]",
                "-fps_mode", "vfr", "-enc_time_base", "1/12000",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(song),
            ], check=True)
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=blue:s=64x36:r=12:d=0.5",
                "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(card),
            ], check=True)
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
                "-c:a", "flac", str(mix),
            ], check=True)
            final = root / "final.mp4"
            result = call("append-outro", "--song-video", str(song), "--outro-video", str(card),
                          "--mix-audio", str(mix), "--output", str(final))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("constant frame rate", result.stderr)
            self.assertFalse(final.exists())

    def test_bundle_rejects_unconfirmed_or_escaping_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "owned.txt"
            source.write_text("synthetic fixture", encoding="utf-8")
            config = root / "bundle.json"
            data = {"schema_version": 1, "assets": [{
                "source": str(source), "destination": "../escape.txt",
                "rights_status": "review-needed", "permission_ref": "none",
            }]}
            config.write_text(json.dumps(data), encoding="utf-8")
            result = call("bundle", "--config", str(config), "--output-dir", str(root / "out"))
            self.assertNotEqual(result.returncode, 0)
            data["assets"][0]["rights_status"] = "owned"
            config.write_text(json.dumps(data), encoding="utf-8")
            result = call("bundle", "--config", str(config), "--output-dir", str(root / "out"))
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / "escape.txt").exists())
            data["assets"][0]["destination"] = "exports/owned.txt"
            config.write_text(json.dumps(data), encoding="utf-8")
            external = root / "external"
            external.mkdir()
            output = root / "out"
            output.mkdir()
            (output / "exports").symlink_to(external, target_is_directory=True)
            result = call("bundle", "--config", str(config), "--output-dir", str(output))
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((external / "owned.txt").exists())

            unlisted = root / "unlisted-output"
            unlisted.mkdir()
            (unlisted / "private-link").symlink_to(external, target_is_directory=True)
            result = call("bundle", "--config", str(config), "--output-dir", str(unlisted))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unlisted", result.stderr)
            self.assertFalse((unlisted / "manifest.json").exists())

            data["assets"].append({
                "source": str(source), "destination": "exports/owned.txt/child.txt",
                "rights_status": "owned", "permission_ref": "demo",
            })
            config.write_text(json.dumps(data), encoding="utf-8")
            conflicting = root / "conflicting-output"
            result = call("bundle", "--config", str(config), "--output-dir", str(conflicting))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("conflict", result.stderr)
            self.assertFalse(conflicting.exists())

            data["assets"] = [{
                "source": str(source), "destination": "exports/owned.txt",
                "rights_status": "owned", "permission_ref": 123,
            }]
            config.write_text(json.dumps(data), encoding="utf-8")
            result = call("bundle", "--config", str(config),
                          "--output-dir", str(root / "numeric-permission-ref"))
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
