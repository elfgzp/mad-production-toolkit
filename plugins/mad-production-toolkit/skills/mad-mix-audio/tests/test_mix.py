"""Behavior checks using generated tones; no bundled third-party media."""

from __future__ import annotations

import array
import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "mix.py"
RATE = 48000


def tone(path: Path, seconds: float, amplitude_at) -> None:
    samples = array.array("h")
    for n in range(round(seconds * RATE)):
        t = n / RATE
        value = amplitude_at(t) * math.sin(2 * math.pi * 220 * t)
        samples.append(round(max(-1, min(1, value)) * 32767))
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(RATE)
        writer.writeframes(samples.tobytes())


def render(folder: Path, config: dict, name: str) -> Path:
    config_path = folder / f"{name}.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(config_path)],
        text=True, capture_output=True,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return folder / config["output"]


def samples(path: Path) -> array.array:
    raw = subprocess.check_output([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-f", "f32le", "-ac", "2", "-ar", str(RATE), "pipe:1",
    ])
    output = array.array("f")
    output.frombytes(raw)
    return output


def rms(data: array.array, start: float, end: float, channel: int = 0) -> float:
    first, last = round(start * RATE), round(end * RATE)
    values = (data[2 * i + channel] for i in range(first, last))
    return math.sqrt(sum(value * value for value in values) / (last - first))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class MixTests(unittest.TestCase):
    def test_timeline_pan_automation_and_24_bit_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            tone(folder / "lead.wav", 2, lambda _: 0.1)
            config = {
                "version": 1,
                "duration_sec": 3,
                "sample_rate": RATE,
                "output": "mix.flac",
                "stems": [{
                    "name": "lead", "path": "lead.wav", "bus": "guitars",
                    "source_start_sec": 0.2, "source_end_sec": 1.8,
                    "timeline_start_sec": 0.5, "placement": "mono", "pan": -1,
                    "highpass_hz": 80,
                    "eq": [
                        {"type": "peak", "frequency_hz": 3200, "width": 1, "gain_db": -2},
                        {"type": "high_shelf", "frequency_hz": 6000, "width": 0.8, "gain_db": -2},
                    ],
                    "reverb": {"delay_ms": [38], "decay": [0.1], "wet": 0.1},
                }],
                "buses": {"guitars": {"automation": [
                    {"time_sec": 0, "gain_db": 0},
                    {"time_sec": 0.9, "gain_db": 0},
                    {"time_sec": 1.0, "gain_db": 6},
                ]}},
                "master": {"gain_db": -6, "limiter": {"limit_db": -1}},
            }
            output = render(folder, config, "timed")
            probe = json.loads(subprocess.check_output([
                "ffprobe", "-v", "error", "-show_entries",
                "stream=bits_per_raw_sample,sample_fmt,channels:format=duration",
                "-of", "json", str(output),
            ]))
            self.assertEqual(probe["streams"][0]["bits_per_raw_sample"], "24")
            self.assertEqual(probe["streams"][0]["channels"], 2)
            self.assertAlmostEqual(float(probe["format"]["duration"]), 3, places=2)
            data = samples(output)
            self.assertLess(rms(data, 0.1, 0.3), 0.0001)
            self.assertGreater(rms(data, 0.65, 0.85), 0.01)
            self.assertLess(rms(data, 1.2, 1.4, 1), 0.0001)
            self.assertGreater(rms(data, 1.2, 1.4) / rms(data, 0.65, 0.85), 1.8)
            self.assertLess(rms(data, 2.5, 2.7), 0.0001)

    def test_bass_bus_compression_reduces_level_spread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            tone(folder / "bass.wav", 2, lambda t: 0.05 if t < 1 else 0.8)
            # A cabinet/NAM/IR layer is represented as ordinary pre-rendered audio.
            tone(folder / "cabinet.wav", 2, lambda t: 0.02 if t < 1 else 0.25)
            common = {
                "version": 1, "duration_sec": 2, "sample_rate": RATE,
                "stems": [
                    {"name": "dry bass", "path": "bass.wav", "bus": "bass"},
                    {"name": "rendered cabinet", "path": "cabinet.wav", "bus": "bass"},
                ],
                "master": {"gain_db": -9},
            }
            dry = render(folder, {**common, "output": "dry.flac"}, "dry")
            compressed = render(folder, {
                **common, "output": "compressed.flac",
                "buses": {"bass": {"compressor": {
                    "threshold_db": -18, "ratio": 4,
                    "attack_ms": 5, "release_ms": 100,
                    "detection": "rms", "makeup_db": 0,
                }}},
            }, "compressed")
            a, b = samples(dry), samples(compressed)
            spread_before = rms(a, 1.25, 1.75) / rms(a, 0.25, 0.75)
            spread_after = rms(b, 1.25, 1.75) / rms(b, 0.25, 0.75)
            self.assertGreater(spread_before, 10)
            self.assertLess(spread_after, spread_before * 0.7)


if __name__ == "__main__":
    unittest.main()
