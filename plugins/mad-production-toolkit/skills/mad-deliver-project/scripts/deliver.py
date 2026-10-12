#!/usr/bin/env python3
"""QA, append an outro, bundle authorized assets, and ZIP a video with its mix."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from fractions import Fraction
from pathlib import Path, PurePosixPath

RIGHTS = {"owned", "licensed", "permission"}
LABEL = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{command[0]} failed: {result.stderr[-2500:]}")
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stream_sha256(stream: object) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):  # type: ignore[attr-defined]
        digest.update(block)
    return digest.hexdigest()


def probe(path: Path, count_frames: bool = False) -> dict:
    command = ["ffprobe", "-v", "error"]
    if count_frames:
        command.append("-count_frames")
    command.extend(["-show_format", "-show_streams", "-of", "json", str(path)])
    return json.loads(run(command).stdout)


def video_stream(data: dict) -> dict | None:
    return next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"), None)


def audio_stream(data: dict) -> dict | None:
    return next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"), None)


def duration_seconds(data: dict) -> float:
    value = data.get("format", {}).get("duration")
    if value is None:
        raise ValueError("media duration is unavailable")
    return float(value)


def stream_duration(stream: dict) -> Fraction:
    ticks, time_base = stream.get("duration_ts"), stream.get("time_base")
    if ticks not in (None, "N/A") and time_base not in (None, "N/A"):
        return Fraction(int(ticks)) * Fraction(time_base)
    value = stream.get("duration")
    if value in (None, "N/A"):
        raise ValueError("stream duration is unavailable")
    return Fraction(str(value))


def frame_count(stream: dict) -> int:
    value = stream.get("nb_read_frames")
    if value in (None, "N/A"):
        raise ValueError("decoded video frame count is unavailable")
    return int(value)


def require_constant_frame_rate(path: Path, rate: Fraction, expected_frames: int) -> None:
    result = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
                  "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(path)])
    frames = json.loads(result.stdout).get("frames", [])
    if len(frames) != expected_frames:
        raise ValueError("song video needs a constant frame rate and readable frame timestamps")
    try:
        start = Fraction(frames[0]["best_effort_timestamp_time"])
        tolerance = min(Fraction(1, 1000), Fraction(1, 50) / rate)
        for index, frame in enumerate(frames):
            timestamp = Fraction(frame["best_effort_timestamp_time"])
            if abs(timestamp - start - index / rate) > tolerance:
                raise ValueError("song video must have a constant frame rate; normalize it before delivery")
    except (IndexError, KeyError, TypeError) as exc:
        raise ValueError("song video needs a constant frame rate and readable frame timestamps") from exc


def require_new_output(path: Path, replace: bool) -> None:
    if path.exists() and not replace:
        raise FileExistsError(f"output exists; pass --replace to overwrite: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".write-", delete=False) as tmp:
        tmp.write(content)
        temporary = Path(tmp.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def loudness(path: Path) -> dict[str, str]:
    result = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
                  "-map", "0:a:0", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
                  "-f", "null", "-"])
    matches = re.findall(r"\{\s*\"input_i\".*?\}", result.stderr, flags=re.DOTALL)
    if not matches:
        raise RuntimeError("FFmpeg did not return loudness measurements")
    values = json.loads(matches[-1])
    return {"integrated_lufs": values["input_i"],
            "true_peak_dbtp": values["input_tp"], "lra_lu": values["input_lra"]}


def qa(args: argparse.Namespace) -> None:
    path = args.video.resolve(strict=True)
    if args.report and args.report.resolve() == path:
        raise ValueError("QA report must not overwrite the video")
    if args.duration_tolerance < 0 or args.av_tolerance < 0:
        raise ValueError("duration tolerances must be nonnegative")
    data = probe(path, count_frames=True)
    videos = [stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"]
    audios = [stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"]
    if len(videos) != 1 or len(audios) > 1:
        raise ValueError("QA requires exactly one video and at most one audio stream")
    video = video_stream(data)
    audio = audio_stream(data)
    if video is None:
        raise ValueError("final video has no video stream")
    if audio is None and not args.allow_silent:
        raise ValueError("final video has no audio stream; use --allow-silent for a video-only card")
    frames = frame_count(video)
    if args.expect_frames is not None and frames != args.expect_frames:
        raise ValueError(f"frame count {frames} differs from expected {args.expect_frames}")
    duration = duration_seconds(data)
    if args.expect_duration is not None and abs(duration - args.expect_duration) > args.duration_tolerance:
        raise ValueError(f"duration {duration:.6f} s differs from expected {args.expect_duration:.6f} s")
    video_duration = float(stream_duration(video))
    if audio:
        audio_duration = float(stream_duration(audio))
        if abs(audio_duration - video_duration) > args.av_tolerance:
            raise ValueError(f"audio/video stream durations differ by "
                             f"{abs(audio_duration - video_duration):.6f} s")
    decode = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-xerror", "-i", str(path),
              "-map", "0:v:0"]
    if audio:
        decode.extend(["-map", "0:a:0"])
    run(decode + ["-f", "null", "-"])
    report = {
        "schema_version": 1, "filename": path.name, "size_bytes": path.stat().st_size,
        "sha256": sha256(path), "full_decode": "passed", "frames": frames,
        "duration_seconds": duration,
        "video_duration_seconds": video_duration,
        "video": {"codec": video.get("codec_name"), "width": video.get("width"),
                  "height": video.get("height"), "frame_rate": video.get("avg_frame_rate")},
    }
    if audio:
        report["audio_duration_seconds"] = audio_duration
        report["audio_video_duration_gap_seconds"] = abs(audio_duration - video_duration)
        report["audio"] = {"codec": audio.get("codec_name"),
                           "sample_rate": audio.get("sample_rate"),
                           "channels": audio.get("channels")}
        report["loudness"] = loudness(path)
    else:
        report["audio"] = None
    content = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.report:
        atomic_text(args.report.resolve(), content)
    print(content, end="")


def append_outro(args: argparse.Namespace) -> None:
    song = args.song_video.resolve(strict=True)
    outro = args.outro_video.resolve(strict=True)
    mix = args.mix_audio.resolve(strict=True)
    output = args.output.resolve()
    if output in {song, outro, mix}:
        raise ValueError("output must be different from all inputs")
    require_new_output(output, args.replace)
    song_data = probe(song, count_frames=True)
    outro_data = probe(outro, count_frames=True)
    mix_data = probe(mix)
    sv = video_stream(song_data)
    ov = video_stream(outro_data)
    ma = audio_stream(mix_data)
    if sv is None or ov is None or ma is None:
        raise ValueError("song and card need video streams; mix needs an audio stream")
    try:
        rate = Fraction(sv.get("avg_frame_rate") or sv.get("r_frame_rate"))
        card_rate = Fraction(ov.get("avg_frame_rate") or ov.get("r_frame_rate"))
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError("song and card must have usable frame rates") from exc
    if rate <= 0 or rate > 240:
        raise ValueError("song frame rate is unavailable or invalid")
    if card_rate <= 0 or card_rate > 240:
        raise ValueError("card frame rate is unavailable or invalid")
    fps = f"{rate.numerator}/{rate.denominator}"
    width, height = int(sv["width"]), int(sv["height"])
    if width % 2 or height % 2:
        raise ValueError("song dimensions must be even for yuv420p output")
    song_frames = frame_count(sv)
    require_constant_frame_rate(song, rate, song_frames)
    source_card_frames = frame_count(ov)
    outro_frames = round(Fraction(source_card_frames) * rate / card_rate)
    if outro_frames < 1:
        raise ValueError("card is too short for the target frame rate")
    total_frames = song_frames + outro_frames
    song_duration = song_frames / float(rate)
    total_duration = total_frames / float(rate)
    if args.mix_tolerance < 0 or args.audio_rate <= 0:
        raise ValueError("mix tolerance must be nonnegative and audio rate must be positive")
    source_rate = int(ma["sample_rate"])
    if source_rate <= 0:
        raise ValueError("mix sample rate must be positive")
    picture_duration = Fraction(song_frames) / rate
    mix_duration = stream_duration(ma)
    if mix_duration + Fraction(1, source_rate) < picture_duration:
        raise ValueError("mix is shorter than the song picture; refusing to pad silence inside the song")
    if mix_duration - picture_duration > Fraction(str(args.mix_tolerance)):
        raise ValueError("mix is longer than the song picture by more than mix tolerance")
    scale = (f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
             f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p")
    graph = ";".join((
        f"[0:v]fps={fps},trim=end_frame={song_frames},setpts=PTS-STARTPTS,{scale}[song]",
        f"[1:v]fps={fps},trim=end_frame={outro_frames},setpts=PTS-STARTPTS,{scale}[card]",
        "[song][card]concat=n=2:v=1:a=0[v]",
        f"[2:a]aresample={args.audio_rate},asetpts=PTS-STARTPTS,"
        f"atrim=duration={song_duration:.9f},apad,atrim=duration={total_duration:.9f}[a]",
    ))
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".outro-", suffix=".mp4", delete=False) as tmp:
        temporary = Path(tmp.name)
    try:
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-i", str(song), "-i", str(outro), "-i", str(mix),
             "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
             "-c:v", "libx264", "-preset", args.preset, "-crf", str(args.crf),
             "-pix_fmt", "yuv420p", "-r", fps, "-frames:v", str(total_frames),
             "-c:a", "aac", "-b:a", args.audio_bitrate, "-ar", str(args.audio_rate),
             "-movflags", "+faststart", str(temporary)])
        rendered = probe(temporary, count_frames=True)
        stream = video_stream(rendered)
        if stream is None or frame_count(stream) != total_frames or audio_stream(rendered) is None:
            raise RuntimeError("joined output is missing frames or audio")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"joined {song_frames}+{outro_frames}={total_frames} frames -> {output}")


def relative_destination(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/"):
        raise ValueError("bundle destination must be a relative POSIX path")
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts) or value != path.as_posix():
        raise ValueError("bundle destination must be normalized and stay inside the bundle")
    if path.parts[0] == "manifest.json":
        raise ValueError("manifest.json is reserved")
    return path


def copy_immutable(source: Path, destination: Path, digest: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256(destination) != digest:
            raise FileExistsError(f"bundle destination differs from source: {destination.name}")
        return
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".asset-", delete=False) as tmp:
        temporary = Path(tmp.name)
    try:
        shutil.copyfile(source, temporary)
        if sha256(temporary) != digest:
            raise IOError("asset changed while copying")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def bundle(args: argparse.Namespace) -> None:
    config_path = args.config.resolve(strict=True)
    output = args.output_dir.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or set(config) != {"schema_version", "assets"} or config["schema_version"] != 1:
        raise ValueError("bundle config needs schema_version=1 and assets")
    if not isinstance(config["assets"], list) or not config["assets"]:
        raise ValueError("bundle assets must be a nonempty list")
    planned = []
    destinations: set[str] = set()
    for item in config["assets"]:
        if not isinstance(item, dict) or set(item) != {"source", "destination", "rights_status", "permission_ref"}:
            raise ValueError("each bundle asset needs source, destination, rights_status, permission_ref")
        if (item["rights_status"] not in RIGHTS or
                not isinstance(item["permission_ref"], str) or
                not LABEL.fullmatch(item["permission_ref"])):
            raise ValueError("bundle assets require a declared rights status and path-free permission_ref")
        destination = relative_destination(item["destination"])
        if destination.as_posix() in destinations:
            raise ValueError(f"duplicate bundle destination: {destination}")
        destinations.add(destination.as_posix())
        source = Path(item["source"]).expanduser()
        if not source.is_absolute():
            source = config_path.parent / source
        source = source.resolve(strict=True)
        if not source.is_file():
            raise ValueError("bundle source must be a regular file")
        planned.append((source, destination, item["rights_status"], item["permission_ref"]))
    allowed_directories: set[str] = set()
    for destination in destinations:
        for parent in PurePosixPath(destination).parents:
            if parent == PurePosixPath("."):
                continue
            if parent.as_posix() in destinations:
                raise ValueError(f"bundle destinations conflict: {parent} and {destination}")
            allowed_directories.add(parent.as_posix())
    if output.exists():
        if not output.is_dir():
            raise ValueError("bundle output must be a directory")
        for path in output.rglob("*"):
            relative = path.relative_to(output).as_posix()
            if path.is_symlink():
                raise ValueError(f"bundle has an unlisted or unsafe symbolic link: {relative}")
            if path.is_dir() and relative in allowed_directories:
                continue
            if path.is_file() and relative in destinations | {"manifest.json"}:
                continue
            raise ValueError(f"bundle has an unlisted or conflicting entry: {relative}")
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for source, relative, rights, permission_ref in sorted(planned, key=lambda item: item[1].as_posix()):
        digest = sha256(source)
        target = output / relative
        if not target.resolve().is_relative_to(output):
            raise ValueError("bundle destination follows a link outside the bundle")
        copy_immutable(source, target, digest)
        records.append({"relative_path": relative.as_posix(), "sha256": digest,
                        "size_bytes": source.stat().st_size, "rights_status": rights,
                        "permission_ref": permission_ref})
    manifest = {"schema_version": 1, "assets": records}
    atomic_text(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    print(f"bundled {len(records)} declared-rights assets -> {output / 'manifest.json'}")


def zip_pair(args: argparse.Namespace) -> None:
    video = args.video.resolve(strict=True)
    audio = args.audio.resolve(strict=True)
    output = args.output.resolve()
    if output in {video, audio} or video.name == audio.name:
        raise ValueError("ZIP output and member names must be distinct")
    require_new_output(output, args.replace)
    if video_stream(probe(video)) is None or audio_stream(probe(audio)) is None:
        raise ValueError("ZIP inputs must contain video and audio respectively")
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".delivery-", suffix=".zip", delete=False) as tmp:
        temporary = Path(tmp.name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=1, allowZip64=True) as archive:
            for path in (video, audio):
                archive.write(path, arcname=path.name)
        with zipfile.ZipFile(temporary) as archive:
            if archive.namelist() != [video.name, audio.name]:
                raise RuntimeError("ZIP members differ from requested files")
            if bad := archive.testzip():
                raise RuntimeError(f"ZIP CRC failure: {bad}")
            for path in (video, audio):
                with path.open("rb") as original, archive.open(path.name) as packed:
                    if stream_sha256(original) != stream_sha256(packed):
                        raise RuntimeError(f"ZIP SHA-256 mismatch: {path.name}")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"verified 2-member ZIP -> {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    append = commands.add_parser("append-outro", help="join song picture, silent card, and lossless mix")
    append.add_argument("--song-video", type=Path, required=True)
    append.add_argument("--outro-video", type=Path, required=True)
    append.add_argument("--mix-audio", type=Path, required=True)
    append.add_argument("--output", type=Path, required=True)
    append.add_argument("--mix-tolerance", type=float, default=0.02,
                        help="maximum excess mix duration in seconds; a short mix is rejected")
    append.add_argument("--preset", default="medium")
    append.add_argument("--crf", type=int, default=18)
    append.add_argument("--audio-bitrate", default="320k")
    append.add_argument("--audio-rate", type=int, default=48000)
    append.add_argument("--replace", action="store_true")
    append.set_defaults(func=append_outro)
    check = commands.add_parser("qa", help="probe, fully decode, and measure final video")
    check.add_argument("--video", type=Path, required=True)
    check.add_argument("--expect-frames", type=int)
    check.add_argument("--expect-duration", type=float)
    check.add_argument("--duration-tolerance", type=float, default=0.1)
    check.add_argument("--av-tolerance", type=float, default=0.05,
                       help="maximum difference between audio and video stream durations in seconds")
    check.add_argument("--allow-silent", action="store_true")
    check.add_argument("--report", type=Path)
    check.set_defaults(func=qa)
    collect = commands.add_parser("bundle", help="copy only explicitly authorized assets")
    collect.add_argument("--config", type=Path, required=True)
    collect.add_argument("--output-dir", type=Path, required=True)
    collect.set_defaults(func=bundle)
    archive = commands.add_parser("zip", help="package one video and one audio with CRC/SHA-256 file checks")
    archive.add_argument("--video", type=Path, required=True)
    archive.add_argument("--audio", type=Path, required=True)
    archive.add_argument("--output", type=Path, required=True)
    archive.add_argument("--replace", action="store_true")
    archive.set_defaults(func=zip_pair)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
