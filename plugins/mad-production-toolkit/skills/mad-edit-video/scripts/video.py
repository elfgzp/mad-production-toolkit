#!/usr/bin/env python3
"""Render a cached multicamera base, add alpha layers, or replace its soundtrack."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def probe(path: Path) -> dict:
    result = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,avg_frame_rate,nb_frames,duration,pix_fmt:format=duration",
        "-of", "json", str(path),
    ], capture_output=True, text=True, check=True)
    payload = json.loads(result.stdout)
    if not payload.get("streams"):
        raise ValueError(f"No video stream: {path}")
    stream = payload["streams"][0]
    stream["duration_seconds"] = float(stream.get("duration") or payload["format"]["duration"])
    return stream


def resolve(base: Path, name: str) -> Path:
    path = Path(name).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def cache_key(config: Path, paths: list[Path]) -> dict:
    version = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, check=True)
    return {
        "config_sha256": sha256(config),
        "inputs": {str(index): {"sha256": sha256(path), "name": path.name}
                   for index, path in enumerate(paths)},
        "ffmpeg": version.stdout.splitlines()[0],
    }


def atomic_render(command: list[str], output: Path, *, sidecar: Path | None = None,
                  key: dict | None = None) -> None:
    """Keep any previous render intact until FFmpeg has completed successfully."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output.stem}-", dir=output.parent) as name:
        temporary = Path(name) / output.name
        run([*command[:-1], str(temporary)])
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RuntimeError(f"FFmpeg produced no output: {temporary}")
        if sidecar is not None:
            if key is None:
                raise ValueError("cache key is required with a sidecar")
            metadata = {**key, "output_sha256": sha256(temporary)}
            staged_sidecar = Path(name) / sidecar.name
            staged_sidecar.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, output)
        if sidecar is not None:
            os.replace(staged_sidecar, sidecar)


def finite(value: object, name: str, minimum: float = 0) -> float:
    number = float(value)
    if not math.isfinite(number) or number < minimum:
        raise ValueError(f"{name} must be finite and >= {minimum}")
    return number


def video_settings(payload: dict) -> tuple[int, int, Fraction, float, int]:
    canvas = payload.get("canvas")
    if not isinstance(canvas, list) or len(canvas) != 2:
        raise ValueError("canvas must be [width, height]")
    width, height = (int(item) for item in canvas)
    if min(width, height) < 2 or max(width, height) > 8192 or width % 2 or height % 2:
        raise ValueError("canvas dimensions must be positive, even, and <=8192")
    fps = Fraction(payload["fps"])
    if not 0 < fps <= 120:
        raise ValueError("fps must be within 0–120")
    duration = finite(payload.get("duration_seconds"), "duration_seconds", 0.001)
    frames = round(duration * fps)
    if frames < 1:
        raise ValueError("duration is shorter than one frame")
    return width, height, fps, duration, frames


def hex_color(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError("background_color must be #RRGGBB")
    return "0x" + value[1:]


def dimensions(path: Path) -> tuple[int, int]:
    result = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "json", str(path),
    ], check=True, capture_output=True, text=True)
    streams = json.loads(result.stdout).get("streams", [])
    if not streams:
        raise ValueError(f"No visual stream in layer: {path}")
    return int(streams[0]["width"]), int(streams[0]["height"])


def grade_filter(panel: dict) -> list[str]:
    parts: list[str] = []
    eq = panel.get("eq")
    if eq is not None:
        if not isinstance(eq, dict) or set(eq) - {"contrast", "brightness", "saturation"}:
            raise ValueError("eq accepts contrast, brightness, saturation only")
        contrast = finite(eq.get("contrast", 1), "contrast", 0)
        brightness = float(eq.get("brightness", 0))
        saturation = finite(eq.get("saturation", 1), "saturation", 0)
        if not -1 <= brightness <= 1:
            raise ValueError("brightness must be -1..1")
        parts.append(f"eq=contrast={contrast:.4f}:brightness={brightness:.4f}:saturation={saturation:.4f}")
    balance = panel.get("colorbalance")
    if balance is not None:
        if not isinstance(balance, dict) or set(balance) - {"rm", "gm", "bm"}:
            raise ValueError("colorbalance accepts rm, gm, bm only")
        values = {key: float(balance.get(key, 0)) for key in ("rm", "gm", "bm")}
        if any(not -1 <= value <= 1 for value in values.values()):
            raise ValueError("colorbalance values must be -1..1")
        parts.append("colorbalance=" + ":".join(f"{key}={value:.4f}" for key, value in values.items()))
    return parts


def fade_filter(panel: dict, duration: float) -> list[str]:
    parts: list[str] = []
    _, visible_start, visible_end = panel_timing(panel, duration)
    for mode, label in (("in", "fade_in"), ("out", "fade_out")):
        value = panel.get(label)
        if value is None:
            continue
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError(f"{label} must be [start, duration]")
        start = finite(value[0], f"{label}.start")
        length = finite(value[1], f"{label}.duration", 0.001)
        if start < visible_start or start + length > visible_end + 0.02:
            raise ValueError(f"{label} extends beyond panel visible interval")
        parts.append(f"fade=t={mode}:st={start:.6f}:d={length:.6f}")
    return parts


def panel_timing(panel: dict, duration: float) -> tuple[float, float, float]:
    trim = finite(panel.get("trim_start", 0), "panel trim_start")
    start = finite(panel.get("start_seconds", 0), "panel start_seconds")
    end = finite(panel.get("end_seconds", duration), "panel end_seconds")
    if not start < end <= duration + 0.02:
        raise ValueError("panel start/end must lie within song duration")
    return trim, start, end


def base_graph(panels: list[dict], canvas: tuple[int, int], fps: Fraction,
               duration: float) -> str:
    width, height = canvas
    clauses: list[str] = []
    for index, panel in enumerate(panels):
        x, y, pw, ph = (int(panel[key]) for key in ("x", "y", "width", "height"))
        if min(x, y) < 0 or min(pw, ph) < 2 or pw % 2 or ph % 2 or x + pw > width or y + ph > height:
            raise ValueError(f"panel {index}: invalid position or size")
        trim, start, end = panel_timing(panel, duration)
        filters = [f"trim=start={trim:.6f}:duration={end - start:.6f}",
                   "setpts=PTS-STARTPTS", f"fps={fps}",
                   f"setpts=PTS+{start:.6f}/TB"]
        crop = panel.get("crop")
        if crop is not None:
            if not isinstance(crop, list) or len(crop) != 4:
                raise ValueError(f"panel {index}: crop must be [width,height,x,y]")
            cw, ch, cx, cy = (int(value) for value in crop)
            if min(cw, ch) < 2 or min(cx, cy) < 0:
                raise ValueError(f"panel {index}: invalid crop")
            filters.append(f"crop={cw}:{ch}:{cx}:{cy}")
        filters.append(f"scale={pw}:{ph}:flags=lanczos")
        filters.extend(grade_filter(panel))
        filters.extend(fade_filter(panel, duration))
        filters.append("format=yuv420p")
        clauses.append(f"[{index}:v]" + ",".join(filters) + f"[panel{index}]")
    background_index = len(panels)
    clauses.append(f"[{background_index}:v]setpts=PTS-STARTPTS,format=yuv420p[base0]")
    for index, panel in enumerate(panels):
        x, y = int(panel["x"]), int(panel["y"])
        _, start, end = panel_timing(panel, duration)
        clauses.append(f"[base{index}][panel{index}]"
                       f"overlay=x={x}:y={y}:shortest=0:eof_action=pass:repeatlast=0:"
                       f"enable='gte(t,{start:.6f})*lt(t,{end:.6f})':format=auto[base{index + 1}]")
    clauses.append(f"[base{len(panels)}]format=yuv420p[v]")
    return ";".join(clauses)


def render_base(config: Path, output: Path, force: bool) -> None:
    payload = json.loads(config.read_text(encoding="utf-8"))
    width, height, fps, duration, frames = video_settings(payload)
    background_color = hex_color(payload["background_color"])
    panels = payload.get("panels")
    if not isinstance(panels, list) or not 1 <= len(panels) <= 8:
        raise ValueError("panels must contain 1–8 entries")
    sources: list[Path] = []
    for index, panel in enumerate(panels):
        if not isinstance(panel, dict) or not isinstance(panel.get("path"), str):
            raise ValueError(f"panel {index}: path is required")
        path = resolve(config.parent, panel["path"])
        if not path.is_file():
            raise FileNotFoundError(path)
        source_duration = probe(path)["duration_seconds"]
        trim, start, end = panel_timing(panel, duration)
        if source_duration + 0.06 < trim + end - start:
            raise ValueError(f"panel {index}: source ends before requested visible interval")
        sources.append(path)
    key = cache_key(config, sources)
    sidecar = output.with_suffix(output.suffix + ".cache.json")
    if output.resolve() in {path.resolve() for path in sources}:
        raise ValueError("base output must differ from source videos")
    if output.exists():
        try:
            prior = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.is_file() else {}
        except (OSError, json.JSONDecodeError):
            prior = {}
        if (all(prior.get(field) == value for field, value in key.items())
                and prior.get("output_sha256") == sha256(output)):
            print(f"cache hit: {output}")
            return
        if not force:
            raise FileExistsError(f"{output} exists with changed inputs; pass --force to rerender")
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for path in sources:
        command += ["-i", str(path)]
    command += ["-f", "lavfi", "-i", f"color=c={background_color}:s={width}x{height}:r={fps}:d={duration:.6f}"]
    command += ["-filter_complex", base_graph(panels, (width, height), fps, duration),
                "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(fps),
                "-frames:v", str(frames), "-movflags", "+faststart", str(output)]
    atomic_render(command, output, sidecar=sidecar, key=key)
    print(f"{output}\t{frames} frames")


def composite(config: Path, output: Path, audio_override: Path | None, force: bool) -> None:
    if output.exists() and not force:
        raise FileExistsError(f"{output} exists; pass --force to replace")
    payload = json.loads(config.read_text(encoding="utf-8"))
    base = resolve(config.parent, payload["base"])
    if not base.is_file():
        raise FileNotFoundError(base)
    base_info = probe(base)
    layers = payload.get("layers", [])
    if not isinstance(layers, list):
        raise ValueError("layers must be an array")
    sources = [base]
    layer_settings = []
    base_width, base_height = int(base_info["width"]), int(base_info["height"])
    for item in layers:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("every layer needs a path")
        path = resolve(config.parent, item["path"])
        if not path.is_file():
            raise FileNotFoundError(path)
        sources.append(path)
        natural_width, natural_height = dimensions(path)
        layer_width = int(item.get("width", natural_width))
        layer_height = int(item.get("height", natural_height))
        x, y = int(item.get("x", 0)), int(item.get("y", 0))
        if min(x, y) < 0 or min(layer_width, layer_height) < 1 or x + layer_width > base_width or y + layer_height > base_height:
            raise ValueError("layer dimensions or position exceed base canvas")
        start = finite(item.get("start_seconds", 0), "layer start_seconds")
        end = finite(item.get("end_seconds", base_info["duration_seconds"]), "layer end_seconds")
        if not start < end <= base_info["duration_seconds"] + 0.05:
            raise ValueError("layer start/end must lie within base duration")
        opacity = float(item.get("opacity", 1))
        if not math.isfinite(opacity) or not 0 <= opacity <= 1:
            raise ValueError("layer opacity must be 0–1")
        layer_settings.append((x, y, layer_width, layer_height, start, end, opacity))
    audio = audio_override or (resolve(config.parent, payload["audio"]) if payload.get("audio") else None)
    if audio and not audio.is_file():
        raise FileNotFoundError(audio)
    if output.resolve() in {path.resolve() for path in [*sources, *([audio] if audio else [])]}:
        raise ValueError("overlay output must differ from all inputs")
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    fps = base_info["avg_frame_rate"]
    for index, path in enumerate(sources):
        if index and path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            command += ["-loop", "1", "-framerate", fps, "-i", str(path)]
        else:
            command += ["-i", str(path)]
    if audio:
        command += ["-i", str(audio)]
    clauses = ["[0:v]setpts=PTS-STARTPTS[base0]"]
    for index, (x, y, layer_width, layer_height, start, end, opacity) in enumerate(layer_settings, 1):
        clauses.append(f"[{index}:v]setpts=PTS-STARTPTS+{start:.6f}/TB,"
                       f"scale={layer_width}:{layer_height}:flags=lanczos,format=rgba,"
                       f"colorchannelmixer=aa={opacity:.6f}[layer{index}]")
        clauses.append(f"[base{index - 1}][layer{index}]"
                       f"overlay=x={x}:y={y}:shortest=0:repeatlast=0:eof_action=pass:"
                       f"enable='gte(t,{start:.6f})*lt(t,{end:.6f})':format=auto[base{index}]")
    clauses.append(f"[base{len(layers)}]format=yuv420p[v]")
    command += ["-filter_complex", ";".join(clauses), "-map", "[v]"]
    if audio:
        command += ["-map", f"{len(sources)}:a:0", "-c:a", "aac", "-b:a", "320k", "-ar", "48000"]
    else:
        command += ["-an"]
    command += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-pix_fmt", "yuv420p", "-frames:v", str(base_info.get("nb_frames") or
                                                       round(base_info["duration_seconds"] * Fraction(base_info["avg_frame_rate"]))),
                "-movflags", "+faststart", str(output)]
    atomic_render(command, output)
    print(output)


def remux(video: Path, audio: Path, output: Path, force: bool) -> None:
    if output.exists() and not force:
        raise FileExistsError(f"{output} exists; pass --force to replace")
    if not video.is_file() or not audio.is_file():
        raise FileNotFoundError("video and audio inputs must exist")
    if output.resolve() in {video.resolve(), audio.resolve()}:
        raise ValueError("remux output must differ from its inputs")
    length = probe(video)["duration_seconds"]
    atomic_render(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(video), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "320k", "-ar", "48000",
         "-t", f"{length:.6f}", "-movflags", "+faststart", str(output)], output)
    print(output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    base = sub.add_parser("base", help="render/cached textless multicamera video")
    base.add_argument("--config", type=Path, required=True)
    base.add_argument("--output", type=Path, required=True)
    base.add_argument("--force", action="store_true")
    overlay = sub.add_parser("overlay", help="add transparent title, lyrics, and credits")
    overlay.add_argument("--config", type=Path, required=True)
    overlay.add_argument("--audio", type=Path)
    overlay.add_argument("--output", type=Path, required=True)
    overlay.add_argument("--force", action="store_true")
    replace = sub.add_parser("remux", help="replace audio while copying video bitstream")
    replace.add_argument("--video", type=Path, required=True)
    replace.add_argument("--audio", type=Path, required=True)
    replace.add_argument("--output", type=Path, required=True)
    replace.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
            raise RuntimeError("ffmpeg and ffprobe are required")
        if args.command == "base":
            render_base(args.config.resolve(), args.output, args.force)
        elif args.command == "overlay":
            composite(args.config.resolve(), args.output, args.audio, args.force)
        else:
            remux(args.video, args.audio, args.output, args.force)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError, RuntimeError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    main()
