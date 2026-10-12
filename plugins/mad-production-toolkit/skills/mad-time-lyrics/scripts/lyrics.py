#!/usr/bin/env python3
"""Validate bilingual cues, export SRT/LRC, or render an animated alpha overlay."""

from __future__ import annotations

import argparse
import bisect
import json
import math
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:
    raise SystemExit("Pillow is required: python3 -m pip install Pillow") from exc


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    original: str
    translation: str


def load_cues(path: Path, shift: float = 0.0) -> tuple[dict, list[Cue], float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("cues"), list):
        raise ValueError("Cue JSON needs an object with a cues array")
    if not math.isfinite(shift):
        raise ValueError("shift must be finite")
    duration = float(payload["duration_seconds"])
    if not math.isfinite(duration) or not 0 < duration <= 21600:
        raise ValueError("duration_seconds must be within 0–21600")
    previous_end = 0.0
    cues: list[Cue] = []
    for index, item in enumerate(payload["cues"], 1):
        if not isinstance(item, dict):
            raise ValueError(f"cue {index}: expected object")
        start = float(item["start"]) + shift
        end = float(item["end"]) + shift
        original = item.get("original")
        translation = item.get("translation", "")
        if not isinstance(original, str) or not original.strip():
            raise ValueError(f"cue {index}: original must be nonempty text")
        if not isinstance(translation, str):
            raise ValueError(f"cue {index}: translation must be text")
        if not all(math.isfinite(value) for value in (start, end)):
            raise ValueError(f"cue {index}: timestamps must be finite")
        if start < 0 or end <= start or end > duration + 1e-6:
            raise ValueError(f"cue {index}: require 0 <= start < end <= duration")
        if start < previous_end - 1e-6:
            raise ValueError(f"cue {index}: cues overlap or are unordered")
        if any("\r" in value or "\t" in value for value in (original, translation)):
            raise ValueError(f"cue {index}: use plain text without tabs/CR")
        cues.append(Cue(start, end, original.strip(), translation.strip()))
        previous_end = end
    return payload, cues, duration


def srt_time(seconds: float) -> str:
    total = round(seconds * 1000)
    hours, rem = divmod(total, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def lrc_time(seconds: float) -> str:
    centiseconds = round(seconds * 100)
    minutes, rem = divmod(centiseconds, 6000)
    secs, cents = divmod(rem, 100)
    return f"{minutes:02d}:{secs:02d}.{cents:02d}"


def export_cues(payload: dict, cues: list[Cue], destination: Path, force: bool) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    srt = destination / "lyrics.srt"
    lrc = destination / "lyrics.lrc"
    for path in (srt, lrc):
        if path.exists() and not force:
            raise FileExistsError(f"{path} already exists; pass --force to replace")
    blocks = []
    for index, cue in enumerate(cues, 1):
        lines = [cue.original]
        if cue.translation:
            lines.append(cue.translation)
        blocks.append(f"{index}\n{srt_time(cue.start)} --> {srt_time(cue.end)}\n" + "\n".join(lines))
    srt.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    title = payload.get("title", {})
    lrc_lines = ["[offset:0]"]
    if isinstance(title, dict):
        title_parts = [str(title.get(key, "")).strip() for key in ("original", "translation")]
        if title_parts[0]:
            lrc_lines.append("[ti:" + " / ".join(part for part in title_parts if part) + "]")
        if title.get("artist"):
            lrc_lines.append(f"[ar:{title['artist']}]")
    for cue in cues:
        line = cue.original.replace("\n", " ")
        if cue.translation:
            line += " / " + cue.translation.replace("\n", " ")
        lrc_lines.append(f"[{lrc_time(cue.start)}]{line}")
    lrc.write_text("\n".join(lrc_lines) + "\n", encoding="utf-8")
    print(srt)
    print(lrc)


def font_from(path: str | None, size: int) -> ImageFont.ImageFont:
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def rgb(value: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError(f"Expected #RRGGBB color, got {value!r}")
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))


def smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3 - 2 * value)


def eased(value: float, easing: str) -> float:
    value = max(0.0, min(1.0, value))
    if easing == "linear":
        return value
    if easing == "ease-in":
        return value * value
    if easing == "ease-out":
        return 1 - (1 - value) ** 2
    if easing == "smoothstep":
        return smoothstep(value)
    raise ValueError(f"Unsupported easing: {easing}")


def progress(elapsed: float, duration: float, easing: str) -> float:
    return eased(elapsed / duration, easing) if duration else 1.0


def wrap(text: str, font: ImageFont.ImageFont, max_width: int, max_lines: int) -> list[str]:
    if "\n" in text:
        lines = text.split("\n")
        if len(lines) > max_lines or any(not line for line in lines):
            raise ValueError("Explicit lyric line break exceeds layout limit")
    elif font.getlength(text) <= max_width:
        lines = [text]
    else:
        choices = []
        for split in range(1, len(text)):
            left, right = text[:split].strip(), text[split:].strip()
            if not left or not right:
                continue
            lengths = [font.getlength(left), font.getlength(right)]
            if max(lengths) <= max_width:
                choices.append((abs(lengths[0] - lengths[1]), [left, right]))
        if not choices:
            raise ValueError(f"Lyric does not fit at configured font size: {text[:30]!r}")
        lines = min(choices, key=lambda item: item[0])[1]
    if any(font.getlength(line) > max_width for line in lines):
        raise ValueError(f"Lyric exceeds configured width: {text[:30]!r}")
    return lines


@dataclass(frozen=True)
class Artwork:
    cue: Cue
    base: Image.Image
    highlight: Image.Image
    x: int
    y: int
    highlight_bounds: tuple[int, int, int, int]


def make_artwork(cue: Cue, style: dict) -> Artwork:
    width, height = style["canvas"]
    margin_x = int(style["margin_x"])
    margin_y = int(style["margin_y"])
    inset = int(style["inset"])
    font = font_from(style.get("original_font"), int(style["original_size"]))
    translated_font = font_from(style.get("translation_font"), int(style["translation_size"]))
    max_text_width = width - 2 * margin_x - 2 * inset
    original_lines = wrap(cue.original, font, max_text_width, int(style["max_lines"]))
    translated_lines = (wrap(cue.translation, translated_font, max_text_width,
                             int(style["max_lines"])) if cue.translation else [])
    line_height = int(style["original_size"]) + int(style["line_gap"])
    translation_height = int(style["translation_size"]) + int(style["line_gap"])
    plate_height = 2 * inset + len(original_lines) * line_height + len(translated_lines) * translation_height
    content_width = max(
        [font.getlength(line) for line in original_lines]
        + [translated_font.getlength(line) for line in translated_lines]
    )
    plate_width = min(width - 2 * margin_x, math.ceil(content_width + 2 * inset))
    anchor = style["anchor"]
    if anchor.endswith("left"):
        x = margin_x
    elif anchor.endswith("right"):
        x = width - margin_x - plate_width
    else:
        x = (width - plate_width) // 2
    if anchor.startswith("top"):
        y = margin_y
    elif anchor.startswith("bottom"):
        y = height - margin_y - plate_height
    else:
        y = (height - plate_height) // 2
    if min(x, y) < 0 or x + plate_width > width or y + plate_height > height:
        raise ValueError("Lyric plate exceeds canvas safe area")
    base = Image.new("RGBA", (plate_width, plate_height), (0, 0, 0, 0))
    highlight = base.copy()
    base_draw, highlight_draw = ImageDraw.Draw(base), ImageDraw.Draw(highlight)
    opacity = int(style["plate_opacity"])
    if opacity:
        base_draw.rounded_rectangle((0, 0, plate_width - 1, plate_height - 1),
                                    radius=int(style["plate_radius"]),
                                    fill=(*rgb(style["plate_color"]), opacity))
    stroke_width = int(style["stroke_width"])
    stroke_color = (*rgb(style["stroke_color"]), 255)
    for index, line in enumerate(original_lines):
        pos = (inset, inset + index * line_height)
        base_draw.text(pos, line, font=font, fill=(*rgb(style["original_color"]), 255),
                       stroke_width=stroke_width, stroke_fill=stroke_color)
        highlight_draw.text(pos, line, font=font, fill=(*rgb(style["highlight_color"]), 255),
                            stroke_width=stroke_width, stroke_fill=stroke_color)
    for index, line in enumerate(translated_lines):
        pos = (inset, inset + len(original_lines) * line_height + index * translation_height)
        base_draw.text(pos, line, font=translated_font,
                       fill=(*rgb(style["translation_color"]), 255),
                       stroke_width=stroke_width, stroke_fill=stroke_color)
    return Artwork(cue, base, highlight, x, y,
                   (inset, inset,
                    inset + math.ceil(max(font.getlength(line) for line in original_lines)),
                    inset + len(original_lines) * line_height))


def highlighted_plate(artwork: Artwork, time_seconds: float, settings: dict) -> Image.Image:
    plate = artwork.base.copy()
    mode = settings["mode"]
    if mode == "none":
        return plate
    if mode == "static":
        plate.alpha_composite(artwork.highlight)
        return plate
    fraction = progress(time_seconds - artwork.cue.start,
                        float(settings["duration_seconds"]), settings["easing"])
    x0, y0, x1, y1 = artwork.highlight_bounds
    direction = settings["direction"]
    if direction == "left-to-right":
        bounds = (0, 0, x0 + round((x1 - x0) * fraction), plate.height)
    elif direction == "right-to-left":
        bounds = (x1 - round((x1 - x0) * fraction), 0, plate.width, plate.height)
    elif direction == "top-to-bottom":
        bounds = (0, 0, plate.width, y0 + round((y1 - y0) * fraction))
    else:
        bounds = (0, y1 - round((y1 - y0) * fraction), plate.width, plate.height)
    left, top, right, bottom = bounds
    if right > left and bottom > top:
        plate.alpha_composite(artwork.highlight.crop(bounds), (left, top))
    return plate


def motion_state(settings: dict, fraction: float, entering: bool) -> tuple[float, int, int]:
    mode = settings["mode"]
    opacity = fraction if mode in {"fade", "fade-slide"} else 1.0
    if mode not in {"slide", "fade-slide"}:
        return opacity, 0, 0
    distance = round(float(settings["distance_pixels"]) * (1 - fraction))
    vx, vy = {"left": (-1, 0), "right": (1, 0),
              "up": (0, -1), "down": (0, 1)}[settings["direction"]]
    sign = -1 if entering else 1
    return opacity, sign * vx * distance, sign * vy * distance


def composite_clipped(frame: Image.Image, plate: Image.Image, x: int, y: int) -> None:
    left, top = max(0, -x), max(0, -y)
    right = min(plate.width, frame.width - x)
    bottom = min(plate.height, frame.height - y)
    if right > left and bottom > top:
        frame.alpha_composite(plate.crop((left, top, right, bottom)), (x + left, y + top))


def render_frame(artwork: Artwork | None, time_seconds: float, style: dict) -> bytes:
    width, height = style["canvas"]
    frame = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    if artwork is None:
        return frame.tobytes()
    cue = artwork.cue
    entrance_settings = style["entrance"]
    exit_settings = style["exit"]
    entrance = progress(time_seconds - cue.start,
                        float(entrance_settings["duration_seconds"]), entrance_settings["easing"])
    leaving = progress(cue.end - time_seconds,
                       float(exit_settings["duration_seconds"]), exit_settings["easing"])
    entry_opacity, entry_x, entry_y = motion_state(entrance_settings, entrance, entering=True)
    exit_opacity, exit_x, exit_y = motion_state(exit_settings, leaving, entering=False)
    opacity = entry_opacity * exit_opacity
    if opacity <= 0:
        return frame.tobytes()
    plate = highlighted_plate(artwork, time_seconds, style["highlight"])
    if opacity < 1:
        alpha = plate.getchannel("A")
        plate.putalpha(alpha.point([round(index * opacity) for index in range(256)]))
    composite_clipped(frame, plate, artwork.x + entry_x + exit_x,
                      artwork.y + entry_y + exit_y)
    return frame.tobytes()


def render(cues: list[Cue], duration: float, style: dict, output: Path, force: bool) -> None:
    if output.exists() and not force:
        raise FileExistsError(f"{output} already exists; pass --force to replace")
    if output.suffix.lower() != ".mov":
        raise ValueError("Transparent ProRes output must have a .mov extension")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required")
    fps = Fraction(style["fps"])
    if fps <= 0 or fps > 120:
        raise ValueError("fps must be within 0–120")
    width, height = style["canvas"]
    if min(width, height) <= 0 or max(width, height) > 4096:
        raise ValueError("canvas dimensions must be within 1–4096")
    if any(int(style[key]) < 0 for key in ("margin_x", "margin_y", "inset",
                                             "line_gap", "plate_radius", "stroke_width")):
        raise ValueError("layout dimensions must be nonnegative")
    if style["anchor"] not in ("top-left", "top-center", "top-right",
                               "center", "bottom-left", "bottom-center", "bottom-right"):
        raise ValueError("anchor must be a supported canvas position")
    if not 1 <= int(style["max_lines"]) <= 4:
        raise ValueError("max_lines must be 1–4")
    if not 0 <= int(style["plate_opacity"]) <= 255:
        raise ValueError("plate_opacity must be within 0–255")
    if any(int(style[key]) <= 0 for key in ("original_size", "translation_size")):
        raise ValueError("font sizes must be positive")
    validate_animation(style)
    for key in ("plate_color", "original_color", "highlight_color",
                "translation_color", "stroke_color"):
        rgb(style[key])
    artworks = [make_artwork(cue, style) for cue in cues]
    starts = [cue.start for cue in cues]
    frames = round(duration * fps)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pixel_format", "rgba", "-video_size", f"{width}x{height}",
        "-framerate", str(fps), "-i", "pipe:0",
        "-an", "-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le",
        "-alpha_bits", "16", str(output),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert process.stdin is not None
        for number in range(frames):
            t = number / fps
            index = bisect.bisect_right(starts, float(t)) - 1
            active = artworks[index] if index >= 0 and t < cues[index].end else None
            process.stdin.write(render_frame(active, float(t), style))
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


STYLE_KEYS = {
    "fps", "canvas", "margin_x", "margin_y", "inset", "anchor", "max_lines",
    "line_gap", "original_font", "translation_font", "original_size",
    "translation_size", "plate_color", "plate_opacity", "plate_radius",
    "original_color", "highlight_color", "translation_color", "stroke_color",
    "stroke_width", "highlight", "entrance", "exit",
}


def validate_animation(style: dict) -> None:
    easing = {"linear", "ease-in", "ease-out", "smoothstep"}
    highlight = style["highlight"]
    if not isinstance(highlight, dict) or set(highlight) != {"mode", "direction", "duration_seconds", "easing"}:
        raise ValueError("highlight needs mode, direction, duration_seconds, easing")
    if highlight["mode"] not in {"none", "static", "wipe"}:
        raise ValueError("highlight mode must be none, static, or wipe")
    if highlight["direction"] not in {"left-to-right", "right-to-left",
                                       "top-to-bottom", "bottom-to-top"}:
        raise ValueError("highlight direction is invalid")
    if highlight["easing"] not in easing:
        raise ValueError("highlight easing is invalid")
    for name in ("highlight", "entrance", "exit"):
        settings = style[name]
        if name != "highlight":
            if not isinstance(settings, dict) or set(settings) != {
                "mode", "direction", "duration_seconds", "easing", "distance_pixels"
            }:
                raise ValueError(f"{name} needs mode, direction, duration_seconds, easing, distance_pixels")
            if settings["mode"] not in {"none", "fade", "slide", "fade-slide"}:
                raise ValueError(f"{name} mode is invalid")
            if settings["direction"] not in {"up", "down", "left", "right"}:
                raise ValueError(f"{name} direction is invalid")
            if settings["easing"] not in easing:
                raise ValueError(f"{name} easing is invalid")
            distance = settings["distance_pixels"]
            if type(distance) not in (int, float) or not math.isfinite(distance) or distance < 0:
                raise ValueError(f"{name} distance_pixels must be nonnegative and finite")
        value = settings["duration_seconds"]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 60:
            raise ValueError(f"{name} duration_seconds must be within 0–60")


def load_style(path: Path) -> dict:
    style_path = path.resolve(strict=True)
    style = json.loads(style_path.read_text(encoding="utf-8"))
    if not isinstance(style, dict) or set(style) != STYLE_KEYS:
        raise ValueError("Style JSON must specify every style key listed in cue-format.md")
    for key in ("original_font", "translation_font"):
        value = style[key]
        if value is None:
            continue
        if not isinstance(value, str) or not value:
            raise ValueError(f"{key} must be null or a font path")
        font = Path(value).expanduser()
        if not font.is_absolute():
            font = style_path.parent / font
        font = font.resolve(strict=True)
        if not font.is_file():
            raise ValueError(f"{key} must point to a font file")
        style[key] = str(font)
    return style


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "export", "render"):
        item = sub.add_parser(name)
        item.add_argument("--cues", type=Path, required=True)
        item.add_argument("--shift", type=float, default=0.0,
                          help="Optional common time shift in seconds; verify against audio")
        if name == "export":
            item.add_argument("--output-dir", type=Path, required=True)
            item.add_argument("--force", action="store_true")
        if name == "render":
            item.add_argument("--style", type=Path, required=True)
            item.add_argument("--output", type=Path, required=True)
            item.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        payload, cues, duration = load_cues(args.cues, args.shift)
        if args.command == "validate":
            print(f"{len(cues)} valid cues; duration={duration:.3f}s")
        elif args.command == "export":
            export_cues(payload, cues, args.output_dir, args.force)
        else:
            style = load_style(args.style)
            render(cues, duration, style, args.output, args.force)
    except (ValueError, FileNotFoundError, FileExistsError, RuntimeError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    main()
