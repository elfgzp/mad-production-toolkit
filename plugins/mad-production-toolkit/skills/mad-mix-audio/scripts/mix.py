#!/usr/bin/env python3
"""Mix aligned stems from a declarative JSON file into stereo 24-bit FLAC.

Requires Python 3.9+ and FFmpeg. All processing is explicit in the config;
this script does not load neural amp models or impulse responses. Their already
rendered outputs can be supplied as additional stems on the same bus.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shlex
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """A mix description cannot be rendered safely or unambiguously."""


def only_keys(obj: dict, allowed: set[str], where: str) -> None:
    extra = set(obj) - allowed
    if extra:
        raise ConfigError(f"{where}: unknown field(s): {', '.join(sorted(extra))}")


def object_at(value: Any, where: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{where}: expected an object")
    return value


def number(obj: dict, key: str, default: Any = None, *,
           low: float | None = None, high: float | None = None) -> float:
    value = obj.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ConfigError(f"{key}: expected a finite number")
    value = float(value)
    if low is not None and value < low or high is not None and value > high:
        raise ConfigError(f"{key}: outside [{low}, {high}]")
    return value


def fmt(value: float) -> str:
    return f"{value:.9g}"


def gain_filter(value: float) -> str:
    return f"volume={fmt(value)}dB"


def automation_filter(raw: Any, duration: float) -> str:
    if not isinstance(raw, list) or not raw:
        raise ConfigError("automation: expected a nonempty array of keyframes")
    keys: list[tuple[float, float]] = []
    for index, item in enumerate(raw):
        frame = object_at(item, f"automation[{index}]")
        only_keys(frame, {"time_sec", "gain_db"}, f"automation[{index}]")
        t = number(frame, "time_sec", low=0, high=duration)
        db = number(frame, "gain_db", low=-120, high=48)
        if keys and t <= keys[-1][0]:
            raise ConfigError("automation times must increase strictly")
        keys.append((t, db))
    expr = fmt(keys[-1][1])
    for (start, current), (end, following) in reversed(list(zip(keys, keys[1:]))):
        if current == following:
            section = fmt(current)
        else:
            section = (
                f"({fmt(current)}+({fmt(following-current)})"
                f"*(t-{fmt(start)})/{fmt(end-start)})"
            )
        expr = f"if(lt(t,{fmt(end)}),{section},{expr})"
    if keys[0][0] > 0:
        expr = f"if(lt(t,{fmt(keys[0][0])}),{fmt(keys[0][1])},{expr})"
    return f"volume='pow(10,({expr})/20)':eval=frame"


def eq_filters(raw: Any, rate: int) -> list[str]:
    if not isinstance(raw, list):
        raise ConfigError("eq: expected an array")
    result: list[str] = []
    for index, item in enumerate(raw):
        band = object_at(item, f"eq[{index}]")
        only_keys(band, {"type", "frequency_hz", "width", "gain_db"}, f"eq[{index}]")
        kind = band.get("type")
        if kind not in {"peak", "low_shelf", "high_shelf"}:
            raise ConfigError(f"eq[{index}].type: expected peak, low_shelf, or high_shelf")
        frequency = number(band, "frequency_hz", low=1, high=rate / 2 - 1)
        width = number(band, "width", 1, low=0.01, high=10)
        gain = number(band, "gain_db", low=-30, high=30)
        ffname, width_type = {
            "peak": ("equalizer", "q"),
            "low_shelf": ("lowshelf", "s"),
            "high_shelf": ("highshelf", "s"),
        }[kind]
        result.append(
            f"{ffname}=f={fmt(frequency)}:t={width_type}:w={fmt(width)}:g={fmt(gain)}"
        )
    return result


def reverb_filter(raw: Any) -> str:
    effect = object_at(raw, "reverb")
    only_keys(effect, {"delay_ms", "decay", "wet"}, "reverb")
    delays, decays = effect.get("delay_ms"), effect.get("decay")
    if not isinstance(delays, list) or not isinstance(decays, list) or not delays or len(delays) != len(decays):
        raise ConfigError("reverb: delay_ms and decay must be nonempty arrays of equal length")
    checked_delay = [number({"delay": v}, "delay", low=1, high=2000) for v in delays]
    checked_decay = [number({"decay": v}, "decay", low=0, high=1) for v in decays]
    if len(delays) > 16:
        raise ConfigError("reverb: at most 16 echo taps are supported")
    wet = number(effect, "wet", 0.2, low=0, high=1)
    if wet == 0:
        return "anull"
    return (
        "aecho=in_gain=1:out_gain=1:"
        f"delays={'|'.join(map(fmt, checked_delay))}:"
        f"decays={'|'.join(fmt(value * wet) for value in checked_decay)}"
    )


def compressor_filter(raw: Any) -> str:
    comp = object_at(raw, "compressor")
    only_keys(comp, {"threshold_db", "ratio", "attack_ms", "release_ms", "knee", "detection", "makeup_db"}, "compressor")
    threshold = number(comp, "threshold_db", low=-90, high=0)
    ratio = number(comp, "ratio", low=1, high=20)
    attack = number(comp, "attack_ms", 20, low=0.01, high=2000)
    release = number(comp, "release_ms", 200, low=0.01, high=9000)
    knee = number(comp, "knee", 2, low=1, high=8)
    makeup = number(comp, "makeup_db", 0, low=-20, high=20)
    detection = comp.get("detection", "rms")
    if detection not in {"rms", "peak"}:
        raise ConfigError("compressor.detection: expected rms or peak")
    return (
        f"acompressor=threshold={fmt(10 ** (threshold / 20))}:"
        f"ratio={fmt(ratio)}:attack={fmt(attack)}:release={fmt(release)}:"
        f"knee={fmt(knee)}:detection={detection}:makeup={fmt(10 ** (makeup / 20))}"
    )


def pan_filter(position: float, placement: str) -> str:
    if placement == "mono":
        left = math.sqrt((1 - position) / 2) / 2
        right = math.sqrt((1 + position) / 2) / 2
        return (
            f"pan=stereo|c0={fmt(left)}*c0+{fmt(left)}*c1|"
            f"c1={fmt(right)}*c0+{fmt(right)}*c1"
        )
    left = min(1.0, 1.0 - position)
    right = min(1.0, 1.0 + position)
    return f"pan=stereo|c0={fmt(left)}*c0|c1={fmt(right)}*c1"


COMMON_EFFECT_KEYS = {"highpass_hz", "lowpass_hz", "eq", "gain_db", "reverb", "automation"}


def effect_filters(settings: dict, rate: int, duration: float, *,
                   allow_compressor: bool) -> list[str]:
    result: list[str] = []
    if "highpass_hz" in settings:
        value = number(settings, "highpass_hz", low=1, high=rate / 2 - 1)
        result.append(f"highpass=f={fmt(value)}")
    if "lowpass_hz" in settings:
        value = number(settings, "lowpass_hz", low=1, high=rate / 2 - 1)
        result.append(f"lowpass=f={fmt(value)}")
    if "eq" in settings:
        result.extend(eq_filters(settings["eq"], rate))
    if "gain_db" in settings:
        result.append(gain_filter(number(settings, "gain_db", low=-120, high=48)))
    if "reverb" in settings:
        result.append(reverb_filter(settings["reverb"]))
    if allow_compressor and "compressor" in settings:
        result.append(compressor_filter(settings["compressor"]))
    if "automation" in settings:
        result.append(automation_filter(settings["automation"], duration))
    return result


def stem_chain(index: int, stem: dict, rate: int, duration: float,
               sample_count: int) -> str:
    only_keys(stem, {"name", "path", "bus", "source_start_sec", "source_end_sec",
                     "timeline_start_sec", "placement", "pan"} | COMMON_EFFECT_KEYS,
              f"stems[{index}]")
    start = number(stem, "source_start_sec", 0, low=0)
    source_end = stem.get("source_end_sec")
    if source_end is not None:
        source_end = number(stem, "source_end_sec", low=0)
        if source_end <= start:
            raise ConfigError(f"stems[{index}]: source_end_sec must exceed source_start_sec")
    timeline = number(stem, "timeline_start_sec", 0, low=0, high=duration)
    position = number(stem, "pan", 0, low=-1, high=1)
    placement = stem.get("placement", "mono")
    if placement not in {"mono", "stereo"}:
        raise ConfigError(f"stems[{index}].placement: expected mono or stereo")
    trim = f"atrim=start={fmt(start)}"
    if source_end is not None:
        trim += f":end={fmt(source_end)}"
    stages = [trim, "asetpts=N/SR/TB", f"aresample={rate}",
              "aformat=sample_fmts=fltp:channel_layouts=stereo"]
    # Timeline automation follows delay; all keyframe times describe final mix time.
    stages.extend(effect_filters({k: v for k, v in stem.items() if k != "automation"},
                                 rate, duration, allow_compressor=False))
    stages.append(pan_filter(position, placement))
    if timeline:
        delay = round(timeline * 1000)
        stages.append(f"adelay={delay}|{delay}")
    stages += ["apad", f"atrim=end_sample={sample_count}", "asetpts=N/SR/TB"]
    if "automation" in stem:
        stages.append(automation_filter(stem["automation"], duration))
    return f"[{index}:a:0]{','.join(stages)}[s{index}]"


def build_graph(config: dict) -> tuple[str, list[Path], Path, int]:
    only_keys(config, {"version", "duration_sec", "sample_rate", "output", "stems", "buses", "master"}, "config")
    if type(config.get("version")) is not int or config["version"] != 1:
        raise ConfigError("version: expected 1")
    duration = number(config, "duration_sec", low=0.001, high=86400)
    rate = number(config, "sample_rate", 48000, low=8000, high=192000)
    if not rate.is_integer():
        raise ConfigError("sample_rate must be an integer")
    rate = int(rate)
    sample_count = round(duration * rate)
    raw_stems = config.get("stems")
    if not isinstance(raw_stems, list) or not raw_stems:
        raise ConfigError("stems: expected a nonempty array")
    raw_buses = config.get("buses", {})
    if not isinstance(raw_buses, dict):
        raise ConfigError("buses: expected an object")
    output = config.get("output")
    if not isinstance(output, str) or not output.lower().endswith(".flac"):
        raise ConfigError("output: expected a FLAC path")
    graph: list[str] = []
    inputs: list[Path] = []
    grouped: dict[str, list[str]] = {}
    seen_names: set[str] = set()
    for i, raw in enumerate(raw_stems):
        stem = object_at(raw, f"stems[{i}]")
        name, path, bus = stem.get("name"), stem.get("path"), stem.get("bus", "main")
        if not isinstance(name, str) or not name.strip() or name in seen_names:
            raise ConfigError(f"stems[{i}].name: expected a unique nonempty name")
        seen_names.add(name)
        if not isinstance(path, str) or not path.strip():
            raise ConfigError(f"stems[{i}].path: expected a path")
        if not isinstance(bus, str) or not bus.strip():
            raise ConfigError(f"stems[{i}].bus: expected a nonempty name")
        inputs.append(Path(path))
        grouped.setdefault(bus, []).append(f"[s{i}]")
        graph.append(stem_chain(i, stem, rate, duration, sample_count))
    extra_buses = set(raw_buses) - set(grouped)
    if extra_buses:
        raise ConfigError(f"buses with no stems: {', '.join(sorted(extra_buses))}")
    bus_outputs: list[str] = []
    for i, (name, labels) in enumerate(grouped.items()):
        bus = object_at(raw_buses.get(name, {}), f"buses.{name}")
        only_keys(bus, COMMON_EFFECT_KEYS | {"compressor"}, f"buses.{name}")
        stages = effect_filters(bus, rate, duration, allow_compressor=True)
        if len(labels) > 1:
            stages.insert(0, f"amix=inputs={len(labels)}:duration=longest:normalize=0:dropout_transition=0")
        if not stages:
            stages = ["anull"]
        graph.append(f"{''.join(labels)}{','.join(stages)}[b{i}]")
        bus_outputs.append(f"[b{i}]")
    master = object_at(config.get("master", {}), "master")
    only_keys(master, {"gain_db", "limiter"}, "master")
    master_stages: list[str] = []
    if len(bus_outputs) > 1:
        master_stages.append(
            f"amix=inputs={len(bus_outputs)}:duration=longest:normalize=0:dropout_transition=0"
        )
    if "gain_db" in master:
        master_stages.append(gain_filter(number(master, "gain_db", low=-120, high=48)))
    if "limiter" in master:
        limiter = object_at(master["limiter"], "master.limiter")
        only_keys(limiter, {"limit_db", "attack_ms", "release_ms"}, "master.limiter")
        limit_db = number(limiter, "limit_db", -1, low=-20, high=-0.01)
        attack = number(limiter, "attack_ms", 5, low=0.1, high=20)
        release = number(limiter, "release_ms", 50, low=1, high=8000)
        master_stages.append(
            f"alimiter=limit={fmt(10 ** (limit_db / 20))}:attack={fmt(attack)}:"
            f"release={fmt(release)}:level=0:latency=1"
        )
    master_stages += ["apad", f"atrim=end_sample={sample_count}", "asetpts=PTS-STARTPTS"]
    graph.append(f"{''.join(bus_outputs)}{','.join(master_stages)}[mix]")
    return ";".join(graph), inputs, Path(output), rate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="JSON mix description")
    parser.add_argument("--output", type=Path, help="override config output path")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="FFmpeg executable")
    parser.add_argument("--force", action="store_true", help="replace an existing output")
    parser.add_argument("--dry-run", action="store_true", help="validate and print FFmpeg command")
    args = parser.parse_args()
    try:
        config_path = args.config.expanduser().resolve()
        config = object_at(json.loads(config_path.read_text(encoding="utf-8")), "config")
        graph, raw_inputs, raw_output, rate = build_graph(config)
        inputs = [(config_path.parent / p.expanduser()).resolve() if not p.expanduser().is_absolute()
                  else p.expanduser().resolve() for p in raw_inputs]
        output = args.output if args.output is not None else raw_output
        output = output.expanduser()
        output = output.resolve() if args.output is not None else (config_path.parent / output).resolve()
        if output.suffix.lower() != ".flac":
            raise ConfigError("output must use a .flac extension")
        if any(not p.is_file() for p in inputs):
            missing = [str(p) for p in inputs if not p.is_file()]
            raise ConfigError("missing input file(s): " + ", ".join(missing))
        if output in inputs:
            raise ConfigError("output path must differ from every input path")
        if output.exists() and not args.force:
            raise ConfigError(f"output exists (use --force): {output}")
        temporary = output.with_name(f".{output.stem}.{uuid.uuid4().hex}.partial.flac")
        command = [args.ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostdin", "-y"]
        for path in inputs:
            command += ["-i", str(path)]
        command += [
            "-filter_complex", graph, "-map", "[mix]", "-ar", str(rate), "-ac", "2",
            "-c:a", "flac", "-sample_fmt", "s32", "-bits_per_raw_sample", "24", str(temporary),
        ]
        if args.dry_run:
            print(shlex.join(command))
            return 0
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(command, check=True)
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
        print(output)
        return 0
    except (ConfigError, json.JSONDecodeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"mix: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
