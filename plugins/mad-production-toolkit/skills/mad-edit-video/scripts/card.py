#!/usr/bin/env python3
"""Render a declarative title, performer-credit overlay, or closing card."""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def color(value: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError(f"Invalid color {value!r}; use #RRGGBB")
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))


def font(path: str | None, size: int, root: Path) -> ImageFont.ImageFont:
    if size <= 0:
        raise ValueError("Font size must be positive")
    if path:
        source = Path(path).expanduser()
        source = source if source.is_absolute() else (root / source).resolve()
        return ImageFont.truetype(str(source), size)
    return ImageFont.load_default(size=size)


def finite(value: object, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def background(size: tuple[int, int], payload: dict) -> Image.Image:
    width, height = size
    mode = payload.get("background")
    if mode == "transparent":
        return Image.new("RGBA", size, (0, 0, 0, 0))
    if mode == "solid":
        return Image.new("RGBA", size, (*color(payload["color"]), 255))
    if mode == "gradient":
        top = color(payload["top_color"])
        bottom = color(payload["bottom_color"])
        image = Image.new("RGBA", size)
        draw = ImageDraw.Draw(image)
        for y in range(height):
            weight = y / max(1, height - 1)
            shade = tuple(round(top[channel] * (1 - weight) + bottom[channel] * weight)
                          for channel in range(3))
            draw.line((0, y, width, y), fill=(*shade, 255))
        return image
    raise ValueError("background must be transparent, solid, or gradient")


def intersect(a: tuple[int, int, int, int], b: tuple[int, int, int, int], gap: int) -> bool:
    return not (a[2] + gap <= b[0] or b[2] + gap <= a[0]
                or a[3] + gap <= b[1] or b[3] + gap <= a[1])


def draw_elements(image: Image.Image, elements: list[dict], root: Path,
                  gap: int) -> None:
    width, height = image.size
    draw = ImageDraw.Draw(image)
    occupied: list[tuple[int, int, int, int]] = []
    for index, item in enumerate(elements):
        if not isinstance(item, dict):
            raise ValueError(f"element {index}: expected object")
        kind = item.get("type")
        x = round(finite(item.get("x"), "x"))
        y = round(finite(item.get("y"), "y"))
        align = item.get("align", "center")
        if align not in ("center", "left", "right"):
            raise ValueError(f"element {index}: align must be center, left, or right")
        if kind == "text":
            text = item.get("text")
            if not isinstance(text, str) or not text.strip() or "\n" in text:
                raise ValueError(f"element {index}: text must be a nonempty single line")
            face = font(item.get("font"), int(item["size"]), root)
            bbox = draw.textbbox((0, 0), text, font=face,
                                 stroke_width=int(item.get("stroke_width", 0)))
            item_width, item_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
            left = x - item_width // 2 if align == "center" else (x if align == "left" else x - item_width)
            top = y - item_height // 2
            bounds = (left, top, left + item_width, top + item_height)
            action = ("text", text, face, (left - bbox[0], top - bbox[1]), item)
        elif kind == "image":
            name = item.get("path")
            if not isinstance(name, str):
                raise ValueError(f"element {index}: image path required")
            source = Path(name).expanduser()
            source = source if source.is_absolute() else (root / source).resolve()
            if not source.is_file():
                raise FileNotFoundError(source)
            mark = Image.open(source).convert("RGBA")
            maximum = (int(item.get("max_width", mark.width)),
                       int(item.get("max_height", mark.height)))
            if min(maximum) <= 0:
                raise ValueError(f"element {index}: max image dimensions must be positive")
            mark.thumbnail(maximum, Image.Resampling.LANCZOS)
            left = x - mark.width // 2 if align == "center" else (x if align == "left" else x - mark.width)
            top = y - mark.height // 2
            bounds = (left, top, left + mark.width, top + mark.height)
            action = ("image", mark, (left, top))
        else:
            raise ValueError(f"element {index}: type must be text or image")
        if bounds[0] < 0 or bounds[1] < 0 or bounds[2] > width or bounds[3] > height:
            raise ValueError(f"element {index}: outside canvas")
        if not item.get("allow_overlap") and any(intersect(bounds, old, gap) for old in occupied):
            raise ValueError(f"element {index}: overlaps or is too close to another element")
        occupied.append(bounds)
        if kind == "text":
            _, text, face, point, source_item = action
            draw.text(point, text, font=face, fill=(*color(source_item["color"]), 255),
                      stroke_width=int(source_item.get("stroke_width", 0)),
                      stroke_fill=(*color(source_item["stroke_color"]), 255)
                      if int(source_item.get("stroke_width", 0)) else None)
        else:
            _, mark, point = action
            image.alpha_composite(mark, point)


def smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3 - 2 * value)


def ease(value: float, mode: str) -> float:
    value = max(0.0, min(1.0, value))
    if mode == "linear":
        return value
    if mode == "smoothstep":
        return smoothstep(value)
    raise ValueError("easing must be linear or smoothstep")


def motion_config(item: dict, duration: float) -> dict:
    motion = item.get("motion", {})
    if not isinstance(motion, dict):
        raise ValueError("element motion must be an object")
    allowed = {"start_seconds", "end_seconds", "fade_in_seconds", "fade_out_seconds",
               "offset_from", "offset_to", "scale_from", "scale_to", "opacity", "easing"}
    if set(motion) - allowed:
        raise ValueError("element motion has unknown fields")
    start = finite(motion.get("start_seconds", 0), "motion start_seconds")
    end = finite(motion.get("end_seconds", duration), "motion end_seconds")
    fade_in = finite(motion.get("fade_in_seconds", 0), "motion fade_in_seconds")
    fade_out = finite(motion.get("fade_out_seconds", 0), "motion fade_out_seconds")
    if not 0 <= start < end <= duration or fade_in + fade_out > end - start:
        raise ValueError("element motion timing exceeds card duration")
    offsets = []
    for key in ("offset_from", "offset_to"):
        value = motion.get(key, [0, 0])
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError(f"{key} must be [dx,dy]")
        offsets.append(tuple(finite(part, key) for part in value))
    scale_from = finite(motion.get("scale_from", 1), "scale_from")
    scale_to = finite(motion.get("scale_to", 1), "scale_to")
    opacity = finite(motion.get("opacity", 1), "opacity")
    if min(scale_from, scale_to) <= 0 or max(scale_from, scale_to) > 8 or opacity > 1:
        raise ValueError("motion scale must be within 0–8 and opacity within 0–1")
    easing = motion.get("easing", "linear")
    ease(0.5, easing)
    return {"start": start, "end": end, "fade_in": fade_in, "fade_out": fade_out,
            "offset_from": offsets[0], "offset_to": offsets[1],
            "scale_from": scale_from, "scale_to": scale_to,
            "opacity": opacity, "easing": easing}


def draw_motion(frame: Image.Image, mark: Image.Image, origin: tuple[int, int],
                spec: dict, time_seconds: float) -> None:
    if not spec["start"] <= time_seconds < spec["end"]:
        return
    progress = ease((time_seconds - spec["start"]) / (spec["end"] - spec["start"]),
                    spec["easing"])
    scale = spec["scale_from"] + (spec["scale_to"] - spec["scale_from"]) * progress
    width = max(1, round(mark.width * scale))
    height = max(1, round(mark.height * scale))
    current = mark.resize((width, height), Image.Resampling.LANCZOS)
    dx = spec["offset_from"][0] + (spec["offset_to"][0] - spec["offset_from"][0]) * progress
    dy = spec["offset_from"][1] + (spec["offset_to"][1] - spec["offset_from"][1]) * progress
    x = round(origin[0] + (mark.width - width) / 2 + dx)
    y = round(origin[1] + (mark.height - height) / 2 + dy)
    if x < 0 or y < 0 or x + width > frame.width or y + height > frame.height:
        raise ValueError("animated element moves outside canvas")
    opacity = spec["opacity"]
    if spec["fade_in"]:
        opacity *= ease((time_seconds - spec["start"]) / spec["fade_in"], spec["easing"])
    if spec["fade_out"]:
        opacity *= ease((spec["end"] - time_seconds) / spec["fade_out"], spec["easing"])
    if opacity < 1:
        channel = current.getchannel("A")
        current.putalpha(channel.point([round(value * opacity) for value in range(256)]))
    frame.alpha_composite(current, (x, y))


def render(payload: dict, root: Path, output: Path, force: bool) -> None:
    if output.exists() and not force:
        raise FileExistsError(f"{output} exists; pass --force to replace")
    canvas = payload.get("canvas")
    if not isinstance(canvas, list) or len(canvas) != 2:
        raise ValueError("canvas must be [width,height]")
    size = tuple(int(value) for value in canvas)
    if min(size) <= 0 or max(size) > 8192:
        raise ValueError("canvas dimensions must be 1–8192")
    elements = payload.get("elements")
    if not isinstance(elements, list):
        raise ValueError("elements array required")
    base_background = background(size, payload)
    image = base_background.copy()
    draw_elements(image, elements, root, int(payload["min_gap"]))
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".png":
        if any("motion" in item for item in elements):
            raise ValueError("element motion requires a video output")
        image.save(output)
        print(output)
        return
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg required for video output")
    fps = Fraction(payload["fps"])
    duration = finite(payload.get("duration_seconds"), "duration_seconds")
    if not 0 < fps <= 120 or not 0 < duration <= 600:
        raise ValueError("fps or duration outside supported range")
    frames = round(duration * fps)
    is_alpha = payload["background"] == "transparent"
    suffix = output.suffix.lower()
    if is_alpha and suffix != ".mov":
        raise ValueError("transparent cards must be .mov or .png")
    if not is_alpha and suffix != ".mp4":
        raise ValueError("opaque video cards must be .mp4 or .png")
    fade_in = finite(payload["fade_in_seconds"], "fade_in_seconds")
    fade_out = finite(payload["fade_out_seconds"], "fade_out_seconds")
    if min(fade_in, fade_out) < 0 or fade_in + fade_out > duration:
        raise ValueError("fade times exceed card duration")
    fade_easing = payload["fade_easing"]
    ease(0.5, fade_easing)
    fade_color = color(payload["fade_color"]) if not is_alpha else None
    prepared = []
    for item in elements:
        layer = Image.new("RGBA", size, (0, 0, 0, 0))
        draw_elements(layer, [item], root, 0)
        box = layer.getbbox()
        if box is None:
            raise ValueError("element has no visible pixels")
        prepared.append((layer.crop(box), (box[0], box[1]), motion_config(item, duration)))
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-f", "rawvideo", "-pixel_format", "rgba",
               "-video_size", f"{size[0]}x{size[1]}", "-framerate", str(fps),
               "-i", "pipe:0", "-an"]
    if is_alpha:
        command += ["-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le",
                    "-alpha_bits", "16"]
    else:
        command += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-pix_fmt", "yuv420p"]
    command += ["-frames:v", str(frames), str(output)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert process.stdin is not None
        for number in range(frames):
            time_seconds = number / fps
            in_weight = ease(float(time_seconds / fade_in), fade_easing) if fade_in else 1.0
            out_weight = ease(float((duration - time_seconds) / fade_out), fade_easing) if fade_out else 1.0
            opacity = min(in_weight, out_weight)
            frame = base_background.copy()
            for mark, point, spec in prepared:
                draw_motion(frame, mark, point, spec, float(time_seconds))
            if is_alpha:
                channel = frame.getchannel("A")
                frame.putalpha(channel.point([round(value * opacity) for value in range(256)]))
            elif opacity < 1:
                fade_canvas = Image.new("RGBA", size, (*fade_color, 255))
                frame = Image.blend(fade_canvas, frame, opacity)
            process.stdin.write(frame.tobytes())
        process.stdin.close()
        assert process.stderr is not None
        error = process.stderr.read().decode("utf-8", errors="replace")
        if process.wait() != 0:
            raise RuntimeError(error[-2000:])
    except Exception:
        process.kill()
        process.wait()
        output.unlink(missing_ok=True)
        raise
    print(f"{output}\t{frames} frames")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        config = args.config.resolve()
        render(json.loads(config.read_text(encoding="utf-8")), config.parent,
               args.output, args.force)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    main()
