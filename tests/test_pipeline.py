"""Run the public toolkit as a two-second, fully synthetic MAD project."""

from __future__ import annotations

from array import array
import hashlib
import importlib.util
import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
SKILLS = REPOSITORY / "plugins/mad-production-toolkit/skills"
RATE = 48_000
FPS = 12
SONG_SECONDS = 1.5
SONG_FRAMES = 18
OUTRO_FRAMES = 6


def script(skill: str, name: str) -> Path:
    result = SKILLS / skill / "scripts" / name
    if not result.is_file():
        raise AssertionError(f"Missing installed skill script: {result}")
    return result


def run(*command: str | Path) -> str:
    arguments = [str(value) for value in command]
    result = subprocess.run(arguments, capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(
            f"Command failed ({result.returncode}): {' '.join(arguments[:3])}\n"
            f"stdout:\n{result.stdout[-2000:]}\nstderr:\n{result.stderr[-4000:]}"
        )
    return result.stdout


def python(skill: str, name: str, *arguments: str | Path) -> str:
    return run(sys.executable, script(skill, name), *arguments)


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def stream(path: Path, kind: str) -> dict:
    payload = json.loads(run(
        "ffprobe", "-v", "error", "-select_streams", f"{kind}:0",
        "-show_entries", "stream=nb_frames,avg_frame_rate,pix_fmt,sample_rate,channels,bits_per_raw_sample",
        "-of", "json", path,
    ))
    return payload["streams"][0]


def frame_bytes(path: Path, number: int, pixel_format: str) -> bytes:
    result = subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-vf", f"select=eq(n\\,{number})", "-frames:v", "1",
        "-f", "rawvideo", "-pix_fmt", pixel_format, "pipe:1",
    ], capture_output=True, check=True)
    return result.stdout


def tone(path: Path, frequency: float) -> None:
    samples = array("h")
    for number in range(round(1.75 * RATE)):
        seconds = number / RATE
        transient = 0.14 if any(0 <= seconds - onset < 0.005 for onset in (0.3, 0.85, 1.3)) else 0
        value = 0.10 * math.sin(2 * math.pi * frequency * seconds) + transient
        samples.append(round(value * 32767))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes(samples.tobytes())


@unittest.skipUnless(
    shutil.which("ffmpeg") and shutil.which("ffprobe")
    and importlib.util.find_spec("numpy") and importlib.util.find_spec("PIL"),
    "FFmpeg, NumPy, and Pillow required",
)
class SyntheticPipelineTest(unittest.TestCase):
    def test_ingest_to_verified_delivery(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mad-pipeline-") as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            sources = root / "synthetic-sources"
            sources.mkdir()

            # All source footage and audio are generated here, with fictional labels.
            assets = []
            for asset_id, color in (("scene-red", "red"), ("scene-blue", "blue")):
                source = sources / f"{asset_id}.mp4"
                run("ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=12:d=2",
                    "-an", "-c:v", "mpeg4", source)
                assets.append({"id": asset_id, "path": str(source), "media_type": "video",
                               "origin": {"type": "label", "value": "synthetic_fixture"},
                               "creator": "Example Studio", "rights_status": "owned"})
            for asset_id, frequency in (("lead", 330), ("rhythm", 220), ("bass", 110)):
                source = sources / f"{asset_id}.wav"
                tone(source, frequency)
                assets.append({"id": asset_id, "path": str(source), "media_type": "audio",
                               "origin": {"type": "label", "value": "synthetic_fixture"},
                               "creator": "Example Studio", "rights_status": "owned"})
            asset_config = root / "assets.json"
            write_json(asset_config, {"schema_version": 1, "assets": assets})
            python("mad-source-assets", "ingest_assets.py", "--config", asset_config,
                   "--project", project)
            manifest_path = project / "assets-manifest.json"
            manifest_text = manifest_path.read_text(encoding="utf-8")
            self.assertNotIn(str(root), manifest_text)
            manifest = json.loads(manifest_text)
            self.assertEqual(len(manifest["assets"]), 5)
            ingested = {item["id"]: project / item["relative_path"] for item in manifest["assets"]}
            for item in manifest["assets"]:
                self.assertEqual(item["sha256"], hashlib.sha256(ingested[item["id"]].read_bytes()).hexdigest())

            shots = root / "shots.json"
            write_json(shots, {
                "schema_version": 2, "fps": "12/1", "width": 160, "height": 90,
                "default_style": {
                    "composition": {"mode": "contain", "anchor_x": 0.5,
                                    "anchor_y": 0.5, "background": "#101018"},
                    "color": {"mode": "none"},
                    "transition": {"in": {"type": "cut"}, "out": {"type": "cut"}},
                },
                "shots": [
                    {"id": "opening", "source_id": "scene-red", "source_in_seconds": 0,
                     "duration_frames": 9, "section": "intro", "beat_hint": "bar 1"},
                    {"id": "response", "source_id": "scene-blue", "source_in_seconds": 0.25,
                     "duration_frames": 9, "section": "answer", "beat_hint": "bar 2"},
                ],
            })
            python("mad-plan-shots", "render_shots.py", "--project", project,
                   "--plan", shots, "--validate-only")
            python("mad-plan-shots", "render_shots.py", "--project", project,
                   "--plan", shots)
            board = json.loads((project / "exports/shot-board-manifest.json").read_text())
            self.assertEqual(board["frames"], SONG_FRAMES)
            panel = project / "exports/animation-panel.mp4"
            self.assertEqual(int(stream(panel, "v")["nb_frames"]), SONG_FRAMES)
            first = frame_bytes(panel, 0, "rgb24")
            second = frame_bytes(panel, 10, "rgb24")
            center = (45 * 160 + 80) * 3
            self.assertGreater(first[center], first[center + 2] + 100)
            self.assertGreater(second[center + 2], second[center] + 100)

            alignment = root / "alignment.json"
            write_json(alignment, {
                "duration_seconds": SONG_SECONDS, "output_dir": "aligned",
                "stems": [
                    {"id": instrument, "input": str(ingested[instrument]),
                     "trim_seconds": 0,
                     "edits": ([{"fade_in": [0.5, 0.55], "fade_out": [1.1, 1.15],
                                 "shift_ms": 20}] if instrument == "lead" else [])}
                    for instrument in ("lead", "rhythm", "bass")
                ],
            })
            python("mad-align-stems", "align.py", "render", "--config", alignment)
            aligned = {name: root / "aligned" / f"{name}_aligned_24bit.flac"
                       for name in ("lead", "rhythm", "bass")}
            audit = json.loads((root / "aligned/alignment_audit.json").read_text())
            self.assertEqual(audit["duration_samples"], round(SONG_SECONDS * RATE))
            self.assertEqual(next(item for item in audit["stems"] if item["id"] == "lead")
                             ["edits"][0]["shift_samples"], 960)
            self.assertTrue(all(path.is_file() for path in aligned.values()))

            mix_config = root / "mix.json"
            mix = root / "mix.flac"
            write_json(mix_config, {
                "version": 1, "duration_sec": SONG_SECONDS, "sample_rate": RATE,
                "output": mix.name,
                "stems": [
                    {"name": "lead", "path": str(aligned["lead"]), "bus": "guitars",
                     "placement": "mono", "pan": 0.5, "gain_db": -5,
                     "automation": [{"time_sec": 0, "gain_db": 0},
                                    {"time_sec": 1.0, "gain_db": 0.5}]},
                    {"name": "rhythm", "path": str(aligned["rhythm"]), "bus": "guitars",
                     "placement": "mono", "pan": -0.5, "gain_db": -6},
                    {"name": "bass", "path": str(aligned["bass"]), "bus": "bass",
                     "placement": "mono", "gain_db": -4},
                ],
                "buses": {"bass": {"compressor": {"threshold_db": -20, "ratio": 2,
                                                   "attack_ms": 20, "release_ms": 120}}},
                "master": {"gain_db": -5, "limiter": {"limit_db": -1}},
            })
            python("mad-mix-audio", "mix.py", mix_config)
            audio_stream = stream(mix, "a")
            self.assertEqual(audio_stream["sample_rate"], str(RATE))
            self.assertEqual(audio_stream["channels"], 2)
            self.assertEqual(audio_stream["bits_per_raw_sample"], "24")

            cues = root / "cues.json"
            write_json(cues, {"duration_seconds": SONG_SECONDS, "cues": [
                {"start": 0.25, "end": 1.25, "original": "Fictional line",
                 "translation": "Example reply"},
            ]})
            python("mad-time-lyrics", "lyrics.py", "validate", "--cues", cues)
            python("mad-time-lyrics", "lyrics.py", "export", "--cues", cues,
                   "--output-dir", root / "subtitles")
            self.assertIn("Example reply", (root / "subtitles/lyrics.srt").read_text())
            lyric_style = json.loads((SKILLS / "mad-time-lyrics/examples/style.json").read_text())
            lyric_style.update({"fps": "12/1", "canvas": [320, 90], "margin_x": 8,
                                "margin_y": 4, "inset": 3, "anchor": "bottom-center",
                                "original_size": 12, "translation_size": 10,
                                "line_gap": 1, "plate_radius": 3})
            lyric_style_path = root / "lyric-style.json"
            write_json(lyric_style_path, lyric_style)
            lyrics = root / "lyrics.mov"
            python("mad-time-lyrics", "lyrics.py", "render", "--cues", cues,
                   "--style", lyric_style_path, "--output", lyrics)
            self.assertEqual(int(stream(lyrics, "v")["nb_frames"]), SONG_FRAMES)
            self.assertIn("yuva", stream(lyrics, "v")["pix_fmt"])
            self.assertTrue(any(frame_bytes(lyrics, 6, "rgba")[3::4]))

            title_config = root / "title.json"
            write_json(title_config, {
                "canvas": [320, 90], "fps": "12/1", "duration_seconds": SONG_SECONDS,
                "background": "transparent", "min_gap": 4,
                "fade_in_seconds": 0.1, "fade_out_seconds": 0.1,
                "fade_easing": "smoothstep",
                "elements": [{"type": "text", "text": "EXAMPLE COVER",
                              "x": 160, "y": 18, "size": 16, "color": "#f3e7ef"}],
            })
            title = root / "title.mov"
            python("mad-edit-video", "card.py", "--config", title_config,
                   "--output", title)
            self.assertEqual(int(stream(title, "v")["nb_frames"]), SONG_FRAMES)
            self.assertIn("yuva", stream(title, "v")["pix_fmt"])
            self.assertTrue(any(frame_bytes(title, 6, "rgba")[3::4]))

            base_config = root / "base.json"
            write_json(base_config, {
                "canvas": [320, 90], "fps": "12/1", "duration_seconds": SONG_SECONDS,
                "background_color": "#101018",
                "panels": [
                    {"path": str(panel), "x": 0, "y": 0, "width": 160, "height": 90},
                    {"path": str(ingested["scene-red"]), "x": 160, "y": 0,
                     "width": 160, "height": 90,
                     "eq": {"contrast": 1.0, "brightness": 0, "saturation": 0.9}},
                ],
            })
            base = root / "base.mp4"
            python("mad-edit-video", "video.py", "base", "--config", base_config,
                   "--output", base)
            self.assertEqual(int(stream(base, "v")["nb_frames"]), SONG_FRAMES)
            overlay_config = root / "overlay.json"
            write_json(overlay_config, {
                "base": str(base),
                "layers": [{"path": str(lyrics), "x": 0, "y": 0},
                           {"path": str(title), "x": 0, "y": 0}],
                "audio": str(mix),
            })
            song_video = root / "song.mp4"
            python("mad-edit-video", "video.py", "overlay", "--config", overlay_config,
                   "--output", song_video)
            self.assertEqual(int(stream(song_video, "v")["nb_frames"]), SONG_FRAMES)
            self.assertEqual(stream(song_video, "a")["channels"], 2)
            self.assertNotEqual(frame_bytes(base, 6, "rgb24"),
                                frame_bytes(song_video, 6, "rgb24"))

            outro_config = root / "outro.json"
            write_json(outro_config, {
                "canvas": [320, 90], "fps": "12/1", "duration_seconds": 0.5,
                "background": "solid", "color": "#261525", "fade_color": "#261525",
                "min_gap": 4, "fade_in_seconds": 0.05, "fade_out_seconds": 0.05,
                "fade_easing": "smoothstep",
                "elements": [{"type": "text", "text": "Thanks for listening",
                              "x": 160, "y": 45, "size": 15, "color": "#f3e7ef"}],
            })
            outro = root / "outro.mp4"
            python("mad-edit-video", "card.py", "--config", outro_config,
                   "--output", outro)
            self.assertEqual(int(stream(outro, "v")["nb_frames"]), OUTRO_FRAMES)

            final = root / "final.mp4"
            python("mad-deliver-project", "deliver.py", "append-outro",
                   "--song-video", song_video, "--outro-video", outro,
                   "--mix-audio", mix, "--output", final)
            qa_path = root / "qa.json"
            python("mad-deliver-project", "deliver.py", "qa", "--video", final,
                   "--expect-frames", str(SONG_FRAMES + OUTRO_FRAMES),
                   "--expect-duration", "2", "--duration-tolerance", "0.1",
                   "--report", qa_path)
            qa_text = qa_path.read_text(encoding="utf-8")
            qa = json.loads(qa_text)
            self.assertEqual(qa["frames"], 24)
            self.assertEqual(qa["full_decode"], "passed")
            self.assertNotIn(str(root), qa_text)
            self.assertNotEqual(frame_bytes(final, 0, "rgb24"),
                                frame_bytes(final, 23, "rgb24"))

            bundle_config = root / "bundle.json"
            write_json(bundle_config, {"schema_version": 1, "assets": [
                {"source": str(final), "destination": "exports/final.mp4",
                 "rights_status": "owned", "permission_ref": "synthetic-fixture"},
                {"source": str(mix), "destination": "exports/mix.flac",
                 "rights_status": "owned", "permission_ref": "synthetic-fixture"},
            ]})
            bundle = root / "bundle"
            python("mad-deliver-project", "deliver.py", "bundle", "--config",
                   bundle_config, "--output-dir", bundle)
            bundle_text = (bundle / "manifest.json").read_text(encoding="utf-8")
            self.assertNotIn(str(root), bundle_text)
            self.assertEqual(len(json.loads(bundle_text)["assets"]), 2)
            archive = root / "delivery.zip"
            python("mad-deliver-project", "deliver.py", "zip", "--video", final,
                   "--audio", mix, "--output", archive)
            with zipfile.ZipFile(archive) as packaged:
                self.assertIsNone(packaged.testzip())
                self.assertEqual(packaged.namelist(), ["final.mp4", "mix.flac"])
                for source in (final, mix):
                    self.assertEqual(hashlib.sha256(packaged.read(source.name)).digest(),
                                     hashlib.sha256(source.read_bytes()).digest())


if __name__ == "__main__":
    unittest.main()
