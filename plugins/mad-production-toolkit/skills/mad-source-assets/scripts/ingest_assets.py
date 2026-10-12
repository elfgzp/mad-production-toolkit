#!/usr/bin/env python3
"""Copy local media into a project and write a portable provenance manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
LABEL_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
RIGHTS = {"owned", "permission", "licensed", "review-needed"}
MEDIA_TYPES = {"video", "audio", "image"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_origin(origin: object) -> dict[str, str]:
    if not isinstance(origin, dict) or set(origin) != {"type", "value"}:
        raise ValueError("origin must have exactly type and value")
    kind, value = origin["type"], origin["value"]
    if not isinstance(value, str) or not value:
        raise ValueError("origin value must be nonempty")
    if kind == "label":
        if not LABEL_RE.fullmatch(value):
            raise ValueError("origin label must be a path-free identifier")
    elif kind == "public_url":
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("origin URL must be a public HTTP(S) URL without credentials")
        # Even unfamiliar signed-URL schemes must never enter the published manifest.
        if "?" in value or "#" in value:
            raise ValueError("origin URL must not contain a query or fragment")
    else:
        raise ValueError("origin type must be public_url or label")
    return {"type": kind, "value": value}


def probe(path: Path, media_type: str) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    raw = json.loads(result.stdout)
    streams = raw.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if media_type in {"video", "image"} and video is None:
        raise ValueError(f"{media_type} asset has no video/image stream")
    if media_type == "audio" and audio is None:
        raise ValueError("audio asset has no audio stream")
    fmt = raw.get("format", {})
    data: dict = {"format": fmt.get("format_name", "unknown")}
    if "duration" in fmt:
        data["duration_seconds"] = float(fmt["duration"])
    if video:
        data["video"] = {
            "codec": video.get("codec_name"), "width": video.get("width"),
            "height": video.get("height"), "frame_rate": video.get("avg_frame_rate"),
        }
    if audio:
        data["audio"] = {
            "codec": audio.get("codec_name"), "sample_rate": audio.get("sample_rate"),
            "channels": audio.get("channels"),
        }
    return data


def atomic_copy(source: Path, destination: Path, expected_hash: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise ValueError(f"asset destination must not be a symbolic link: {destination.name}")
    if destination.exists():
        if sha256(destination) != expected_hash:
            raise FileExistsError(f"asset ID already exists with different bytes: {destination.name}")
        return
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".ingest-", delete=False) as tmp:
        temp = Path(tmp.name)
    try:
        shutil.copyfile(source, temp)
        if sha256(temp) != expected_hash:
            raise IOError("copied asset hash differs from source")
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)


def atomic_json(path: Path, value: dict) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".manifest-", delete=False) as tmp:
        json.dump(value, tmp, ensure_ascii=False, indent=2, sort_keys=True)
        tmp.write("\n")
        temp = Path(tmp.name)
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    config_path = args.config.resolve(strict=True)
    project = args.project.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or set(config) != {"schema_version", "assets"} or config["schema_version"] != 1:
        raise ValueError("asset config must contain schema_version=1 and assets")
    assets = config["assets"]
    if not isinstance(assets, list) or not assets:
        raise ValueError("assets must be a nonempty list")
    ids: set[str] = set()
    validated: list[dict] = []
    for item in assets:
        if not isinstance(item, dict) or set(item) != {"id", "path", "media_type", "origin", "creator", "rights_status"}:
            raise ValueError("each asset needs id, path, media_type, origin, creator, rights_status")
        asset_id = item["id"]
        if not isinstance(asset_id, str) or not ID_RE.fullmatch(asset_id) or asset_id in ids:
            raise ValueError("asset IDs must be unique lowercase path-free identifiers")
        ids.add(asset_id)
        if item["media_type"] not in MEDIA_TYPES or item["rights_status"] not in RIGHTS:
            raise ValueError(f"invalid media_type or rights_status for {asset_id}")
        if not isinstance(item["path"], str) or not item["path"]:
            raise ValueError(f"missing path for {asset_id}")
        if not isinstance(item["creator"], str) or not item["creator"].strip():
            raise ValueError(f"missing creator for {asset_id}")
        origin = validate_origin(item["origin"])
        source = Path(item["path"]).expanduser()
        if not source.is_absolute():
            source = config_path.parent / source
        source = source.resolve(strict=True)
        if not source.is_file():
            raise ValueError(f"source is not a regular file for {asset_id}")
        validated.append({**item, "origin": origin, "_source": source})

    project.mkdir(parents=True, exist_ok=True)
    manifest_path = project / "assets-manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("project asset manifest must not be a symbolic link")
    assets_dir = project / "assets"
    if assets_dir.is_symlink() or not assets_dir.resolve().is_relative_to(project):
        raise ValueError("project assets directory must stay inside the project without links")
    records = []
    for item in sorted(validated, key=lambda value: value["id"]):
        source = item["_source"]
        digest = sha256(source)
        suffix = source.suffix.lower()
        if not suffix or not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
            raise ValueError(f"unsupported filename extension for {item['id']}")
        relative = Path("assets") / f"{item['id']}{suffix}"
        destination = project / relative
        media = probe(source, item["media_type"])
        atomic_copy(source, destination, digest)
        records.append({
            "id": item["id"], "relative_path": relative.as_posix(),
            "sha256": digest, "size_bytes": source.stat().st_size,
            "media_type": item["media_type"], "origin": item["origin"],
            "creator": item["creator"].strip(), "rights_status": item["rights_status"],
            "media": media,
        })
    manifest = {"schema_version": 1, "assets": records}
    atomic_json(manifest_path, manifest)
    print(f"ingested {len(records)} assets -> {manifest_path}")


if __name__ == "__main__":
    main()
