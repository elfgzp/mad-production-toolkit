#!/usr/bin/env python3
"""End-to-end synthetic checks for exact anchors and signed phrase shifts."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "align.py"
SR = 48_000


def command(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def pulse(audio: np.ndarray, at_seconds: float) -> None:
    start = round(at_seconds * SR)
    audio[start : start + 240] = 0.7


def decode(path: Path) -> np.ndarray:
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR),
         "-f", "f32le", "-"],
        capture_output=True,
        check=True,
    )
    return np.frombuffer(result.stdout, dtype="<f4").copy()


def first_attack(audio: np.ndarray, start: float, end: float) -> float:
    a, b = round(start * SR), round(end * SR)
    matches = np.flatnonzero(np.abs(audio[a:b]) > 0.4)
    if not matches.size:
        raise AssertionError(f"No attack in {start}-{end}s")
    return (a + int(matches[0])) / SR


class AlignStemTest(unittest.TestCase):
    def test_signed_shifts_keep_outer_anchors_and_format(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            raw = np.zeros(round(2.4 * SR), dtype=np.float32)
            for t in (0.25, 0.85, 1.55):
                pulse(raw, t + 0.1)
            wav_path = root / "source.wav"
            with wave.open(str(wav_path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(SR)
                wav.writeframes(np.round(raw * 32767).astype("<i2").tobytes())
            config = {
                "duration_seconds": 2.0,
                "output_dir": "./aligned",
                "stems": [
                    {
                        "id": stem_id,
                        "input": "./source.wav",
                        "trim_seconds": 0.1,
                        "edits": [{
                            "fade_in": [0.6, 0.65],
                            "fade_out": [1.3, 1.35],
                            "shift_ms": shift,
                        }],
                    }
                    for stem_id, shift in (("early", 20), ("late", -15))
                ],
            }
            config_path = root / "project.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            rendered = command("render", "--config", str(config_path))
            self.assertEqual(rendered.returncode, 0, rendered.stderr)
            source = decode(wav_path)[round(0.1 * SR) : round(2.1 * SR)]
            expected = {"early": 0.83, "late": 0.865}
            for stem_id, interior_at in expected.items():
                output = root / "aligned" / f"{stem_id}_aligned_24bit.flac"
                aligned = decode(output)
                self.assertEqual(len(aligned), 2 * SR)
                self.assertLess(float(np.max(np.abs(source[:round(0.6 * SR)] - aligned[:round(0.6 * SR)]))), 1e-6)
                self.assertLess(float(np.max(np.abs(source[round(1.35 * SR):] - aligned[round(1.35 * SR):]))), 1e-6)
                self.assertAlmostEqual(first_attack(aligned, 0.18, 0.4), 0.25, delta=1 / SR)
                self.assertAlmostEqual(first_attack(aligned, 1.5, 1.7), 1.55, delta=1 / SR)
                self.assertAlmostEqual(first_attack(aligned, 0.78, 0.92), interior_at, delta=1 / SR)
                metadata = subprocess.run(
                    ["ffprobe", "-v", "error", "-select_streams", "a:0",
                     "-show_entries", "stream=sample_rate,bits_per_raw_sample,channels",
                     "-of", "json", str(output)],
                    text=True, capture_output=True, check=True,
                )
                stream = json.loads(metadata.stdout)["streams"][0]
                self.assertEqual(stream["sample_rate"], "48000")
                self.assertEqual(stream["bits_per_raw_sample"], "24")
                self.assertEqual(stream["channels"], 1)
            audit = json.loads((root / "aligned" / "alignment_audit.json").read_text())
            self.assertEqual(audit["duration_samples"], 2 * SR)
            self.assertEqual(len(audit["stems"]), 2)
            for item in audit["stems"]:
                self.assertEqual(item["max_abs_delta_outside_edits_before_encode"], 0)
                self.assertEqual(item["unchanged_intervals_samples"], [[0, 28800], [64800, 96000]])
            repeat = command("render", "--config", str(config_path))
            self.assertNotEqual(repeat.returncode, 0)
            before = hashlib.sha256((root / "aligned" / "early_aligned_24bit.flac").read_bytes()).hexdigest()
            analysis = command(
                "analyze", "--config", str(config_path), "--stem", "early",
                "--guide", str(wav_path), "--guide-trim-seconds", "0.1",
                "--start", "0", "--end", "1.8", "--rendered",
            )
            self.assertEqual(analysis.returncode, 0, analysis.stderr)
            report = json.loads(analysis.stdout)
            self.assertEqual(report["kind"], "read_only_onset_candidates")
            self.assertIn("not editing instructions", report["warning"])
            self.assertGreaterEqual(len(report["guide_onsets"]), 3)
            after = hashlib.sha256((root / "aligned" / "early_aligned_24bit.flac").read_bytes()).hexdigest()
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
