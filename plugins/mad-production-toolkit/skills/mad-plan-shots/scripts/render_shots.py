#!/usr/bin/env python3
"""Validate a shot plan and render a cached exact-frame animation panel."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

VERSION = 2
ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def number(value: object, field: str, low: float, high: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{field} must be a finite number in [{low}, {high}]")
    return float(value)


def hex_color(value: object, field: str) -> str:
    if not isinstance(value, str) or not COLOR_RE.fullmatch(value):
        raise ValueError(f"{field} must be a #RRGGBB color")
    return "0x" + value[1:].upper()


def validate_style(style: object, frames: int, *, partial: bool = False) -> None:
    if not isinstance(style, dict) or (set(style) - {"composition", "color", "transition"}):
        raise ValueError("style must contain only composition, color, and transition")
    if partial and not style:
        raise ValueError("shot style override must name at least one section")
    if not partial and set(style) != {"composition", "color", "transition"}:
        raise ValueError("default_style must explicitly set composition, color, and transition")
    if "composition" in style:
        composition = style["composition"]
        if not isinstance(composition, dict):
            raise ValueError("composition must be an object")
        mode = composition.get("mode")
        if not isinstance(mode, str):
            raise ValueError("composition.mode must be cover, contain, or stretch")
        fields = {"cover": {"mode", "anchor_x", "anchor_y"},
                  "contain": {"mode", "anchor_x", "anchor_y", "background"},
                  "stretch": {"mode"}}.get(mode)
        if fields is None or set(composition) != fields:
            raise ValueError("composition must explicitly choose cover, contain, or stretch with its required fields")
        if mode != "stretch":
            number(composition["anchor_x"], "composition.anchor_x", 0, 1)
            number(composition["anchor_y"], "composition.anchor_y", 0, 1)
        if mode == "contain":
            hex_color(composition["background"], "composition.background")
    if "color" in style:
        color = style["color"]
        if not isinstance(color, dict) or not isinstance(color.get("mode"), str) or color["mode"] not in {"none", "eq"}:
            raise ValueError("color.mode must be none or eq")
        if color["mode"] == "none":
            if set(color) != {"mode"}:
                raise ValueError("color mode none accepts no adjustment fields")
        else:
            if set(color) - {"mode", "brightness", "contrast", "saturation", "gamma"}:
                raise ValueError("unknown color adjustment field")
            for key, bounds in {"brightness": (-1, 1), "contrast": (0, 3),
                                "saturation": (0, 3), "gamma": (0.1, 10)}.items():
                if key in color:
                    number(color[key], f"color.{key}", *bounds)
    if "transition" in style:
        transition = style["transition"]
        if not isinstance(transition, dict) or set(transition) != {"in", "out"}:
            raise ValueError("transition must explicitly set in and out")
        for edge, transition_item in transition.items():
            if not isinstance(transition_item, dict):
                raise ValueError(f"transition.{edge} must be an object")
            kind = transition_item.get("type")
            if kind == "cut":
                if set(transition_item) != {"type"}:
                    raise ValueError(f"transition.{edge} cut accepts no fade fields")
            elif kind == "fade":
                if set(transition_item) != {"type", "frames", "color"}:
                    raise ValueError(f"transition.{edge} fade requires frames and color")
                count = transition_item["frames"]
                if type(count) is not int or not 1 <= count < frames:
                    raise ValueError(f"transition.{edge}.frames must be 1..duration_frames-1")
                hex_color(transition_item["color"], f"transition.{edge}.color")
            else:
                raise ValueError(f"transition.{edge}.type must be cut or fade")


def resolved_style(default_style: dict, shot: dict) -> dict:
    override = shot.get("style", {})
    if "style" in shot:
        validate_style(override, shot["duration_frames"], partial=True)
    style = {**default_style, **override}
    validate_style(style, shot["duration_frames"])
    return style


def run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{command[0]} failed: {result.stderr[-2000:]}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def within_project(project: Path, value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = project / path
    path = path.resolve()
    if not path.is_relative_to(project):
        raise ValueError("output or asset path must remain inside the project")
    return path


def probe_video(path: Path, count: bool = False) -> dict:
    command = ["ffprobe", "-v", "error", "-select_streams", "v:0"]
    if count:
        command.append("-count_frames")
    command.extend(["-show_entries", "stream=width,height,nb_read_frames:format=duration", "-of", "json", str(path)])
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    stream = (data.get("streams") or [None])[0]
    if not stream:
        raise ValueError(f"missing video stream: {path.name}")
    return {"width": stream.get("width"), "height": stream.get("height"),
            "frames": int(stream["nb_read_frames"]) if stream.get("nb_read_frames") not in (None, "N/A") else None,
            "duration": float(data.get("format", {}).get("duration", 0))}


def load_inputs(project: Path, plan_path: Path, manifest_path: Path) -> tuple[dict, dict, Fraction, str, dict]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if (not isinstance(plan, dict) or set(plan) != {"schema_version", "fps", "width", "height", "default_style", "shots"}
            or type(plan["schema_version"]) is not int or plan["schema_version"] != 2):
        raise ValueError("plan must contain schema_version=2, fps, width, height, default_style, shots")
    validate_style(plan["default_style"], 10**9)
    if not isinstance(plan["fps"], str):
        raise ValueError("fps must be a positive rational string such as 30000/1001")
    try:
        fps = Fraction(plan["fps"])
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError("fps must be a positive rational string such as 30000/1001") from exc
    if fps <= 0 or fps > 240 or not re.fullmatch(r"[1-9][0-9]*/[1-9][0-9]*", plan["fps"]):
        raise ValueError("fps must be a positive rational string at most 240")
    for dimension in ("width", "height"):
        value = plan[dimension]
        if type(value) is not int or value < 2 or value % 2:
            raise ValueError(f"{dimension} must be a positive even integer")
    shots = plan["shots"]
    if not isinstance(shots, list) or not shots:
        raise ValueError("shots must be a nonempty list")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("assets"), list):
        raise ValueError("expected schema_version=1 asset manifest")
    assets = {}
    for item in manifest["assets"]:
        asset_id = item.get("id")
        if asset_id in assets:
            raise ValueError(f"duplicate asset ID: {asset_id}")
        assets[asset_id] = item
    ffmpeg_version = subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0]
    used: set[str] = set()
    seen_shots: set[str] = set()
    styles: dict[str, dict] = {}
    for shot in shots:
        required = {"id", "source_id", "source_in_seconds", "duration_frames", "section", "beat_hint"}
        if not isinstance(shot, dict) or not required.issubset(shot) or set(shot) - required - {"style"}:
            raise ValueError("shot fields do not match the shot plan schema")
        if not isinstance(shot["id"], str) or not ID_RE.fullmatch(shot["id"]) or shot["id"] in seen_shots:
            raise ValueError("shot IDs must be unique path-free identifiers")
        seen_shots.add(shot["id"])
        source_id = shot["source_id"]
        if not isinstance(source_id, str) or source_id not in assets:
            raise ValueError(f"unknown source ID: {source_id}")
        asset = assets[source_id]
        if asset.get("media_type") != "video":
            raise ValueError(f"source is not a video: {source_id}")
        if type(shot["duration_frames"]) is not int or shot["duration_frames"] < 1:
            raise ValueError("duration_frames must be a positive integer")
        styles[shot["id"]] = resolved_style(plan["default_style"], shot)
        start = shot["source_in_seconds"]
        if type(start) not in (int, float) or not math.isfinite(start) or start < 0:
            raise ValueError("source_in_seconds must be finite and nonnegative")
        for key in ("section", "beat_hint"):
            if not isinstance(shot[key], str) or not shot[key].strip():
                raise ValueError(f"{key} must be nonempty")
        if source_id not in used:
            path = within_project(project, asset["relative_path"])
            if not path.is_file() or sha256(path) != asset.get("sha256"):
                raise ValueError(f"source hash or file mismatch: {source_id}")
            media = probe_video(path)
            if media["duration"] <= 0:
                raise ValueError(f"source duration unavailable: {source_id}")
            asset["_path"] = path
            asset["_duration"] = media["duration"]
            used.add(source_id)
        end = start + shot["duration_frames"] / float(fps)
        if end > asset["_duration"] + 0.002:
            raise ValueError(f"shot {shot['id']} exceeds source duration; choose a shorter shot or earlier in-point")
    return plan, assets, fps, ffmpeg_version, styles


def cache_key(shot: dict, asset: dict, plan: dict, style: dict, ffmpeg_version: str) -> str:
    payload = {"renderer_version": VERSION, "ffmpeg": ffmpeg_version,
               "source_sha256": asset["sha256"], "shot": shot, "resolved_style": style,
               "fps": plan["fps"], "width": plan["width"], "height": plan["height"],
               "codec": "libx264", "crf": 18}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


def render_clip(path: Path, source: Path, shot: dict, plan: dict, fps: Fraction, style: dict) -> None:
    frames = shot["duration_frames"]
    fps_value = f"{fps.numerator}/{fps.denominator}"
    width, height = plan["width"], plan["height"]
    composition = style["composition"]
    filters = [f"fps={fps_value}"]
    if composition["mode"] == "cover":
        filters.extend([
            f"scale={width}:{height}:force_original_aspect_ratio=increase:force_divisible_by=2:flags=lanczos",
            f"crop={width}:{height}:x=(iw-ow)*{composition['anchor_x']}:y=(ih-oh)*{composition['anchor_y']}",
        ])
    elif composition["mode"] == "contain":
        filters.extend([
            f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos",
            f"pad={width}:{height}:x=(ow-iw)*{composition['anchor_x']}:y=(oh-ih)*{composition['anchor_y']}:"
            f"color={hex_color(composition['background'], 'composition.background')}",
        ])
    else:
        filters.append(f"scale={width}:{height}:flags=lanczos")
    filters.extend(["setsar=1", "format=yuv420p"])
    color = style["color"]
    if color["mode"] == "eq":
        filters.append("eq=" + ":".join(
            f"{key}={color.get(key, neutral)}"
            for key, neutral in (("brightness", 0), ("contrast", 1), ("saturation", 1), ("gamma", 1))
        ))
    for kind in ("in", "out"):
        edge = style["transition"][kind]
        if edge["type"] == "fade":
            first = 0 if kind == "in" else frames - edge["frames"]
            filters.append(
                f"fade=t={kind}:start_frame={first}:nb_frames={edge['frames']}:"
                f"color={hex_color(edge['color'], f'transition.{kind}.color')}"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".shot-", suffix=".mp4", delete=False) as tmp:
        temp = Path(tmp.name)
    try:
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-ss", f"{shot['source_in_seconds']:.9f}", "-i", str(source), "-an",
             "-vf", ",".join(filters), "-frames:v", str(frames),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
             "-pix_fmt", "yuv420p", "-r", fps_value,
             "-video_track_timescale", str(fps.numerator), str(temp)])
        actual = probe_video(temp, count=True)["frames"]
        if actual != frames:
            raise RuntimeError(f"shot {shot['id']} rendered {actual} frames; expected {frames}")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".write-", delete=False) as tmp:
        tmp.write(content)
        temp = Path(tmp.name)
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, help="default: PROJECT_DIR/assets-manifest.json")
    parser.add_argument("--output", default="exports/animation-panel.mp4", help="project-relative panel path")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    project = args.project.resolve(strict=True)
    plan_path = args.plan.resolve(strict=True)
    manifest_path = (args.manifest or project / "assets-manifest.json").resolve(strict=True)
    output = within_project(project, args.output)
    if output.suffix.lower() != ".mp4":
        raise ValueError("panel output must be an MP4")
    if not output.is_relative_to(project / "exports"):
        raise ValueError("panel output must be inside PROJECT_DIR/exports")
    plan, assets, fps, ffmpeg_version, styles = load_inputs(project, plan_path, manifest_path)
    total = sum(shot["duration_frames"] for shot in plan["shots"])
    print(f"validated {len(plan['shots'])} shots, {total} frames, {total / float(fps):.6f} s")
    if args.validate_only:
        return
    cache_dir = project / "cache/shots"
    cache_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    cache_files = []
    start_frame = 0
    for shot in plan["shots"]:
        asset = assets[shot["source_id"]]
        style = styles[shot["id"]]
        key = cache_key(shot, asset, plan, style, ffmpeg_version)
        clip = cache_dir / f"{key}.mp4"
        sidecar = cache_dir / f"{key}.json"
        cache_valid = False
        if clip.is_file() and sidecar.is_file():
            try:
                cached = json.loads(sidecar.read_text(encoding="utf-8"))
                cache_valid = (
                    cached.get("key") == key
                    and cached.get("sha256") == sha256(clip)
                    and probe_video(clip, count=True)["frames"] == shot["duration_frames"]
                )
            except (OSError, ValueError, subprocess.CalledProcessError):
                cache_valid = False
        if not cache_valid:
            render_clip(clip, asset["_path"], shot, plan, fps, style)
            atomic_write(sidecar, json.dumps({"key": key, "sha256": sha256(clip),
                                               "frames": shot["duration_frames"]}, sort_keys=True) + "\n")
        cache_files.append(clip)
        end_frame = start_frame + shot["duration_frames"]
        rows.append({"shot_id": shot["id"], "section": shot["section"],
                     "source_id": shot["source_id"], "source_in_seconds": shot["source_in_seconds"],
                     "start_frame": start_frame, "end_frame_exclusive": end_frame,
                     "duration_frames": shot["duration_frames"], "start_seconds": f"{start_frame / float(fps):.6f}",
                     "beat_hint": shot["beat_hint"], "composition": style["composition"]["mode"],
                     "color": style["color"]["mode"],
                     "transition_in": style["transition"]["in"]["type"],
                     "transition_out": style["transition"]["out"]["type"], "cache_key": key})
        start_frame = end_frame
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=project, prefix=".concat-", suffix=".txt", delete=False) as tmp:
        concat = Path(tmp.name)
        tmp.write("ffconcat version 1.0\n")
        for clip in cache_files:
            quoted = str(clip).replace("'", "'\\''")
            tmp.write(f"file '{quoted}'\n")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".panel-", suffix=".mp4", delete=False) as tmp:
        temp = Path(tmp.name)
    try:
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-safe", "0", "-f", "concat",
             "-i", str(concat), "-an", "-c:v", "copy", "-movflags", "+faststart", str(temp)])
        actual = probe_video(temp, count=True)["frames"]
        if actual != total:
            raise RuntimeError(f"panel rendered {actual} frames; expected {total}")
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)
        concat.unlink(missing_ok=True)
    import io
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    shot_list = project / "exports/shot-list.csv"
    atomic_write(shot_list, stream.getvalue())
    board_manifest = {"schema_version": 2, "renderer_version": VERSION,
                      "fps": f"{fps.numerator}/{fps.denominator}", "frames": total,
                      "duration_seconds": total / float(fps),
                      "panel_relative_path": output.relative_to(project).as_posix(),
                      "panel_sha256": sha256(output),
                      "shot_list_relative_path": shot_list.relative_to(project).as_posix(),
                      "source_manifest_sha256": sha256(manifest_path),
                      "shots": [{"id": row["shot_id"], "cache_key": row["cache_key"]} for row in rows]}
    atomic_write(project / "exports/shot-board-manifest.json",
                 json.dumps(board_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(f"rendered {output} ({actual} frames); cache entries: {len(cache_files)}")


if __name__ == "__main__":
    main()
