# Release decision and file identity

Before packaging, record the destination's chosen integrated-LUFS range and maximum true peak in private project notes. Compare them with `qa.json`'s `loudness.integrated_lufs` and `loudness.true_peak_dbtp`. These are measurements, not pass/fail fields; `qa` does not normalize audio. Reject silence (`-inf`) for a music deliverable even if the command exits successfully. Also record the human picture, synchronization, lyric, and listening decision.

When delivering both an authorized bundle and the two-file ZIP, run this check after `bundle` and `zip`. Replace the final two arguments with the **destination paths inside the bundle manifest**, in video-then-audio order. The ZIP members may have different basenames; their order is set by the `zip --video ... --audio ...` command.

```bash
python3 - qa.json PROJECT_BUNDLE/manifest.json DELIVERY.zip 04_exports/final-video.mp4 04_exports/mix.flac <<'PY'
import hashlib
import json
import sys
import zipfile

qa_path, manifest_path, zip_path, video_dest, audio_dest = sys.argv[1:]
qa = json.load(open(qa_path, encoding="utf-8"))
manifest = json.load(open(manifest_path, encoding="utf-8"))
by_path = {item["relative_path"]: item["sha256"] for item in manifest["assets"]}
assert by_path[video_dest] == qa["sha256"], "bundle video differs from QA video"

with zipfile.ZipFile(zip_path) as archive:
    names = archive.namelist()
    assert len(names) == 2, "ZIP must contain video then audio"
    for name, destination in zip(names, (video_dest, audio_dest)):
        digest = hashlib.sha256()
        with archive.open(name) as member:
            for chunk in iter(lambda: member.read(1024 * 1024), b""):
                digest.update(chunk)
        assert digest.hexdigest() == by_path[destination], f"ZIP member differs: {name}"
print("QA video, bundle, and ZIP are the same frozen release pair")
PY
```

This checks file identity only. A revised picture or mix needs fresh QA, a new bundle manifest, a new ZIP, and a renewed listening decision. If no bundle is delivered, keep the two hashes and selected paths in private release notes and compare the ZIP members with those recorded values.
