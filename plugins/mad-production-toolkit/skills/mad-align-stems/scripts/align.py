#!/usr/bin/env python3
"""Align reviewed phrase passages without changing the surrounding song timeline.

Dependencies: Python 3.10+, NumPy, ffmpeg and ffprobe on PATH. Positive
shift_ms advances a passage: output at time t reads source at t + shift_ms.
The analyze command only reports onset candidates; it never changes audio or
creates edit instructions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


SAMPLE_RATE = 48_000
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


@dataclass(frozen=True)
class Edit:
    fade_in: tuple[float, float]
    fade_out: tuple[float, float]
    shift_ms: float
    bounds: tuple[int, int, int, int]
    shift_samples: int


@dataclass(frozen=True)
class Stem:
    stem_id: str
    input_label: str
    input_path: Path
    trim_seconds: float
    trim_samples: int
    edits: tuple[Edit, ...]


@dataclass(frozen=True)
class Config:
    source_path: Path
    output_dir: Path
    duration_seconds: float
    duration_samples: int
    stems: tuple[Stem, ...]


def finite_number(value: Any, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    if minimum is not None and number < minimum:
        raise ValueError(f"{label} must be >= {minimum}")
    return number


def seconds_to_samples(seconds: float) -> int:
    return round(seconds * SAMPLE_RATE)


def resolve_config_path(config_path: Path, label: str) -> Path:
    path = Path(label).expanduser()
    if not path.is_absolute():
        path = config_path.parent / path
    return path.resolve()


def parse_pair(value: Any, label: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{label} must be a two-number array")
    return (
        finite_number(value[0], f"{label}[0]", minimum=0),
        finite_number(value[1], f"{label}[1]", minimum=0),
    )


def load_config(path: Path) -> Config:
    path = path.expanduser().resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read config {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Config must be a JSON object")
    unknown = set(data) - {"duration_seconds", "output_dir", "stems"}
    if unknown:
        raise ValueError(f"Unknown config fields: {sorted(unknown)}")
    duration = finite_number(data.get("duration_seconds"), "duration_seconds", minimum=0)
    samples = seconds_to_samples(duration)
    if samples < 2:
        raise ValueError("duration_seconds is too short")
    output_label = data.get("output_dir")
    if not isinstance(output_label, str) or not output_label:
        raise ValueError("output_dir must be a non-empty path")
    output_dir = resolve_config_path(path, output_label)
    entries = data.get("stems")
    if not isinstance(entries, list) or not entries:
        raise ValueError("stems must be a non-empty array")

    stems: list[Stem] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        label = f"stems[{index}]"
        if not isinstance(entry, dict):
            raise ValueError(f"{label} must be an object")
        unknown = set(entry) - {"id", "input", "trim_seconds", "edits"}
        if unknown:
            raise ValueError(f"{label} has unknown fields: {sorted(unknown)}")
        stem_id = entry.get("id")
        if not isinstance(stem_id, str) or not ID_PATTERN.fullmatch(stem_id):
            raise ValueError(f"{label}.id must match {ID_PATTERN.pattern}")
        if stem_id in seen:
            raise ValueError(f"Duplicate stem id: {stem_id}")
        seen.add(stem_id)
        input_label = entry.get("input")
        if not isinstance(input_label, str) or not input_label:
            raise ValueError(f"{label}.input must be a non-empty path")
        input_path = resolve_config_path(path, input_label)
        if not input_path.is_file():
            raise ValueError(f"{label}.input does not exist: {input_path}")
        trim = finite_number(entry.get("trim_seconds"), f"{label}.trim_seconds", minimum=0)
        edit_entries = entry.get("edits", [])
        if not isinstance(edit_entries, list):
            raise ValueError(f"{label}.edits must be an array")
        edits: list[Edit] = []
        prior_end = 0
        for edit_index, raw_edit in enumerate(edit_entries):
            edit_label = f"{label}.edits[{edit_index}]"
            if not isinstance(raw_edit, dict):
                raise ValueError(f"{edit_label} must be an object")
            unknown = set(raw_edit) - {"fade_in", "fade_out", "shift_ms"}
            if unknown:
                raise ValueError(f"{edit_label} has unknown fields: {sorted(unknown)}")
            fade_in = parse_pair(raw_edit.get("fade_in"), f"{edit_label}.fade_in")
            fade_out = parse_pair(raw_edit.get("fade_out"), f"{edit_label}.fade_out")
            shift = finite_number(raw_edit.get("shift_ms"), f"{edit_label}.shift_ms")
            a, b, c, d = tuple(
                seconds_to_samples(t) for t in (*fade_in, *fade_out)
            )
            shift_samples = round(shift * SAMPLE_RATE / 1000)
            if not (0 <= a < b < c < d <= samples):
                raise ValueError(f"{edit_label} requires 0 <= a < b < c < d <= duration")
            if b - a < 2 or d - c < 2:
                raise ValueError(f"{edit_label} crossfades must span at least two samples")
            if a < prior_end:
                raise ValueError(f"{edit_label} overlaps the previous edit")
            if shift_samples == 0:
                raise ValueError(f"{edit_label}.shift_ms rounds to zero samples")
            prior_end = d
            edits.append(Edit(fade_in, fade_out, shift, (a, b, c, d), shift_samples))
        stems.append(
            Stem(stem_id, input_label, input_path, trim, seconds_to_samples(trim), tuple(edits))
        )
    return Config(path, output_dir, duration, samples, tuple(stems))


def run(command: list[str], *, input_bytes: bytes | None = None) -> bytes:
    try:
        result = subprocess.run(command, input=input_bytes, capture_output=True, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Required executable is missing: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"{command[0]} failed: {stderr[-1200:]}") from exc
    return result.stdout


def probe_channels(path: Path) -> int:
    payload = run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "stream=channels", "-of", "json", str(path),
        ]
    )
    streams = json.loads(payload).get("streams", [])
    if not streams:
        raise ValueError(f"No audio stream in {path}")
    channels = streams[0].get("channels")
    if not isinstance(channels, int) or channels < 1 or channels > 8:
        raise ValueError(f"Unsupported channel count in {path}: {channels}")
    return channels


def decode(path: Path, channels: int) -> np.ndarray:
    payload = run(
        [
            "ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0",
            "-ac", str(channels), "-ar", str(SAMPLE_RATE),
            "-f", "f32le", "-",
        ]
    )
    samples = np.frombuffer(payload, dtype="<f4")
    if samples.size % channels:
        raise RuntimeError(f"Decoded audio has an incomplete final frame: {path}")
    audio = samples.reshape(-1, channels).copy()
    if not np.all(np.isfinite(audio)):
        raise ValueError(f"Decoded audio contains NaN/Inf: {path}")
    return audio


def smoothstep(length: int) -> np.ndarray:
    positions = np.linspace(0.0, 1.0, length, dtype=np.float32)
    return positions * positions * (3.0 - 2.0 * positions)


def unedited_intervals(stem: Stem, duration_samples: int) -> list[tuple[int, int]]:
    intervals: list[tuple[int, int]] = []
    cursor = 0
    for edit in stem.edits:
        a, _, _, d = edit.bounds
        if cursor < a:
            intervals.append((cursor, a))
        cursor = d
    if cursor < duration_samples:
        intervals.append((cursor, duration_samples))
    return intervals


def apply_edits(raw: np.ndarray, stem: Stem, duration_samples: int) -> tuple[np.ndarray, float]:
    base = stem.trim_samples
    end = base + duration_samples
    if end > raw.shape[0]:
        raise ValueError(f"{stem.stem_id}: source is shorter than trim + duration")
    dry = raw[base:end]
    output = dry.copy()
    for edit in stem.edits:
        a, b, c, d = edit.bounds
        shifted_start = base + a + edit.shift_samples
        shifted_end = base + d + edit.shift_samples
        if shifted_start < 0 or shifted_end > raw.shape[0]:
            raise ValueError(
                f"{stem.stem_id}: shifted source read exceeds input at {a / SAMPLE_RATE:.3f}s"
            )
        wet = raw[shifted_start:shifted_end]
        weight = np.ones(d - a, dtype=np.float32)
        weight[: b - a] = smoothstep(b - a)
        weight[c - a :] = smoothstep(d - c)[::-1]
        output[a:d] = dry[a:d] * (1 - weight[:, None]) + wet * weight[:, None]

    max_delta = 0.0
    for start, stop in unedited_intervals(stem, duration_samples):
        max_delta = max(max_delta, float(np.max(np.abs(output[start:stop] - dry[start:stop]))))
    if max_delta != 0.0:
        raise AssertionError(f"{stem.stem_id}: unedited anchor samples changed")
    return output, max_delta


def encode_flac(audio: np.ndarray, target: Path) -> None:
    channels = audio.shape[1]
    run(
        [
            "ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(SAMPLE_RATE),
            "-ac", str(channels), "-i", "-", "-c:a", "flac",
            "-sample_fmt", "s32", "-bits_per_raw_sample", "24", str(target),
        ],
        input_bytes=audio.astype("<f4", copy=False).tobytes(),
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stem_target(config: Config, stem: Stem) -> Path:
    return config.output_dir / f"{stem.stem_id}_aligned_24bit.flac"


def edit_audit(edit: Edit) -> dict[str, Any]:
    a, b, c, d = edit.bounds
    return {
        "fade_in_seconds": list(edit.fade_in),
        "full_shift_seconds": [b / SAMPLE_RATE, c / SAMPLE_RATE],
        "fade_out_seconds": list(edit.fade_out),
        "window_samples": [a, b, c, d],
        "shift_ms": edit.shift_ms,
        "shift_samples": edit.shift_samples,
        "positive_shift_advances_audio": True,
    }


def render(config: Config, *, overwrite: bool = False) -> list[Path]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    targets = [stem_target(config, stem) for stem in config.stems]
    report_path = config.output_dir / "alignment_audit.json"
    existing = [p for p in [*targets, report_path] if p.exists()]
    if existing and not overwrite:
        raise ValueError(f"Outputs already exist; use --overwrite: {existing}")
    for stem, target in zip(config.stems, targets):
        if target.resolve() == stem.input_path:
            raise ValueError(f"{stem.stem_id}: output would overwrite its input")

    records: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix=".mad-align-", dir=config.output_dir) as temp_name:
        temp_dir = Path(temp_name)
        for stem, target in zip(config.stems, targets):
            channels = probe_channels(stem.input_path)
            raw = decode(stem.input_path, channels)
            aligned, anchor_max_delta = apply_edits(raw, stem, config.duration_samples)
            temp_flac = temp_dir / target.name
            encode_flac(aligned, temp_flac)
            record = {
                "id": stem.stem_id,
                "input": stem.input_label,
                "input_sha256": sha256(stem.input_path),
                "source_trim_seconds": stem.trim_seconds,
                "source_trim_samples": stem.trim_samples,
                "channels": channels,
                "output": target.name,
                "output_sha256": sha256(temp_flac),
                "edits": [edit_audit(edit) for edit in stem.edits],
                "unchanged_intervals_samples": [
                    list(span) for span in unedited_intervals(stem, config.duration_samples)
                ],
                "max_abs_delta_outside_edits_before_encode": anchor_max_delta,
            }
            records.append(record)
        audit = {
            "schema_version": 1,
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "config": str(config.source_path),
            "sample_rate_hz": SAMPLE_RATE,
            "bit_depth": 24,
            "duration_seconds_requested": config.duration_seconds,
            "duration_samples": config.duration_samples,
            "duration_seconds_rendered": config.duration_samples / SAMPLE_RATE,
            "stems": records,
        }
        temp_audit = temp_dir / report_path.name
        temp_audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for target in targets:
            os.replace(temp_dir / target.name, target)
        os.replace(temp_audit, report_path)
    return [*targets, report_path]


def onset_candidates(
    segment: np.ndarray,
    *,
    timeline_start: float,
    min_spacing_ms: float,
    max_candidates: int = 200,
) -> list[dict[str, float]]:
    mono = segment.reshape(-1)
    hop = round(SAMPLE_RATE * 0.010)
    frame = round(SAMPLE_RATE * 0.020)
    if mono.size < frame + hop:
        return []
    frames = np.lib.stride_tricks.sliding_window_view(mono, frame)[::hop]
    window = np.hanning(frame).astype(np.float32)
    spectrum = np.abs(np.fft.rfft(frames * window[None, :], axis=1))
    frequencies = np.fft.rfftfreq(frame, 1 / SAMPLE_RATE)
    low = (frequencies >= 45) & (frequencies < 500)
    mid = (frequencies >= 500) & (frequencies < 6000)
    log_mag = np.log1p(spectrum * 20)
    positive = np.maximum(np.diff(log_mag, axis=0), 0)
    score = positive[:, low].mean(axis=1) + positive[:, mid].mean(axis=1)
    if not score.size:
        return []
    median = float(np.median(score))
    mad = float(np.median(np.abs(score - median)))
    threshold = max(median + 2 * mad, float(np.quantile(score, 0.75)))
    padded = np.pad(score, (1, 1), constant_values=-np.inf)
    candidates = [
        i for i in range(score.size)
        if score[i] > threshold and score[i] >= padded[i] and score[i] > padded[i + 2]
    ]
    candidates.sort(key=lambda i: float(score[i]), reverse=True)
    spacing_frames = max(1, round(min_spacing_ms / 10))
    selected: list[int] = []
    for index in candidates:
        if all(abs(index - prior) >= spacing_frames for prior in selected):
            selected.append(index)
        if len(selected) >= max_candidates:
            break
    selected.sort()
    return [
        {
            "time_seconds": round(
                timeline_start + ((index + 1) * hop + frame / 2) / SAMPLE_RATE, 5
            ),
            "score": round(float(score[index]), 6),
        }
        for index in selected
    ]


def matching_candidates(
    guide: list[dict[str, float]],
    stem: list[dict[str, float]],
    pair_window_ms: float,
) -> list[dict[str, float]]:
    possibilities: list[tuple[float, float, int, int]] = []
    for gi, g in enumerate(guide):
        for si, s in enumerate(stem):
            offset_ms = (s["time_seconds"] - g["time_seconds"]) * 1000
            if abs(offset_ms) <= pair_window_ms:
                possibilities.append(
                    (abs(offset_ms), -(g["score"] + s["score"]), gi, si)
                )
    possibilities.sort()
    used_guide: set[int] = set()
    used_stem: set[int] = set()
    matches: list[dict[str, float]] = []
    for _, _, gi, si in possibilities:
        if gi in used_guide or si in used_stem:
            continue
        used_guide.add(gi)
        used_stem.add(si)
        matches.append(
            {
                "guide_seconds": guide[gi]["time_seconds"],
                "stem_seconds": stem[si]["time_seconds"],
                "stem_minus_guide_ms": round(
                    (stem[si]["time_seconds"] - guide[gi]["time_seconds"]) * 1000, 2
                ),
            }
        )
    matches.sort(key=lambda match: match["guide_seconds"])
    return matches


def timeline_slice(audio: np.ndarray, trim: float, start: float, end: float, label: str) -> np.ndarray:
    a = seconds_to_samples(trim + start)
    b = seconds_to_samples(trim + end)
    if a < 0 or b > audio.shape[0]:
        raise ValueError(f"{label}: requested timeline window exceeds source")
    return audio[a:b, 0]


def analyze(
    config: Config,
    *,
    stem_id: str,
    guide_path: Path,
    guide_trim: float,
    start: float,
    end: float,
    rendered: bool,
    min_spacing_ms: float,
    pair_window_ms: float,
) -> dict[str, Any]:
    stem = next((item for item in config.stems if item.stem_id == stem_id), None)
    if stem is None:
        raise ValueError(f"Unknown stem id: {stem_id}")
    if not (0 <= start < end <= config.duration_samples / SAMPLE_RATE):
        raise ValueError("Require 0 <= start < end <= rendered duration")
    if end - start > 60:
        raise ValueError("Analyze one phrase/window of at most 60 seconds at a time")
    guide_path = guide_path.expanduser().resolve()
    if not guide_path.is_file():
        raise ValueError(f"Guide does not exist: {guide_path}")
    stem_path = stem_target(config, stem) if rendered else stem.input_path
    if not stem_path.is_file():
        raise ValueError(f"Stem does not exist: {stem_path}")
    guide_audio = decode(guide_path, 1)
    stem_audio = decode(stem_path, 1)
    guide_segment = timeline_slice(guide_audio, guide_trim, start, end, "guide")
    stem_segment = timeline_slice(
        stem_audio, 0 if rendered else stem.trim_seconds, start, end, stem_id
    )
    guide_events = onset_candidates(
        guide_segment, timeline_start=start, min_spacing_ms=min_spacing_ms
    )
    stem_events = onset_candidates(
        stem_segment, timeline_start=start, min_spacing_ms=min_spacing_ms
    )
    pairs = matching_candidates(guide_events, stem_events, pair_window_ms)
    offsets = np.array([pair["stem_minus_guide_ms"] for pair in pairs], dtype=np.float64)
    summary = None
    if offsets.size >= 3:
        summary = {
            "pairs": int(offsets.size),
            "median_stem_minus_guide_ms": round(float(np.median(offsets)), 2),
            "q1_ms": round(float(np.quantile(offsets, 0.25)), 2),
            "q3_ms": round(float(np.quantile(offsets, 0.75)), 2),
        }
    return {
        "kind": "read_only_onset_candidates",
        "warning": (
            "Candidate matches are not editing instructions. Confirm common phrase identity, "
            "opening and ending anchors, repeated interior offsets, timbre differences, "
            "and listening before adding any edit to the JSON config."
        ),
        "positive_offset_means": "stem is later than guide",
        "stem_id": stem_id,
        "variant": "rendered" if rendered else "source",
        "timeline_window_seconds": [start, end],
        "guide_trim_seconds": guide_trim,
        "stem_trim_seconds": 0 if rendered else stem.trim_seconds,
        "guide_onsets": guide_events,
        "stem_onsets": stem_events,
        "candidate_pairs": pairs,
        "candidate_summary": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    render_parser = sub.add_parser("render", help="Apply only edits explicitly supplied in JSON")
    render_parser.add_argument("--config", required=True, type=Path)
    render_parser.add_argument("--overwrite", action="store_true")
    analyze_parser = sub.add_parser(
        "analyze", help="Print read-only guide/stem onset candidates; never edit audio"
    )
    analyze_parser.add_argument("--config", required=True, type=Path)
    analyze_parser.add_argument("--stem", required=True)
    analyze_parser.add_argument("--guide", required=True, type=Path)
    analyze_parser.add_argument("--guide-trim-seconds", type=float, default=0)
    analyze_parser.add_argument("--start", type=float, required=True)
    analyze_parser.add_argument("--end", type=float, required=True)
    analyze_parser.add_argument("--rendered", action="store_true")
    analyze_parser.add_argument("--min-spacing-ms", type=float, default=40)
    analyze_parser.add_argument("--pair-window-ms", type=float, default=80)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.command == "render":
            paths = render(config, overwrite=args.overwrite)
            for path in paths:
                print(path)
        else:
            guide_trim = finite_number(
                args.guide_trim_seconds, "--guide-trim-seconds", minimum=0
            )
            min_spacing = finite_number(args.min_spacing_ms, "--min-spacing-ms", minimum=1)
            pair_window = finite_number(args.pair_window_ms, "--pair-window-ms", minimum=1)
            start = finite_number(args.start, "--start", minimum=0)
            end = finite_number(args.end, "--end", minimum=0)
            report = analyze(
                config,
                stem_id=args.stem,
                guide_path=args.guide,
                guide_trim=guide_trim,
                start=start,
                end=end,
                rendered=args.rendered,
                min_spacing_ms=min_spacing,
                pair_window_ms=pair_window,
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
