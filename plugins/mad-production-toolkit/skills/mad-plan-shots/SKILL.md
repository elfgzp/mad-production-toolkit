---
name: mad-plan-shots
description: Use when a beat-informed MAD shot plan needs a frame-accurate animation panel with project-chosen composition, color, transitions, and reusable per-shot cache from manifested local videos.
---

# MAD shot planning

Use this skill when timing local clips to music and rendering an independent animation panel. Beat analysis supplies candidate cut points; review the musical phrase and choose integer frame counts. Keep story section, source in-point, and a beat hint in each shot so later edits remain understandable.

1. Start with the asset manifest from `mad-source-assets` or an equivalent manifest with `id`, project-relative path, SHA-256, and media type. Use [schema v2](references/shots.schema.json) and [fictional example](references/shots.example.json). Source IDs refer to local media, not download URLs.
2. In the project's `shots.json`, explicitly set `default_style`: composition (`contain`, anchored `cover`, or `stretch`), color (`none` or `eq`), and entrance/exit transition (`cut` or a fade to a selected color). Anchors run from 0 (left/top) to 1 (right/bottom); `contain` fills spare space with the selected background. Override any complete style section per shot. There is no automatic center crop or black fade. Fades stay within a shot's assigned frames; they are not overlapping crossfades.
3. Resolve the installed `mad-plan-shots` skill directory to an **absolute path**, then run its script from any working directory: `python3 /absolute/path/to/mad-plan-shots/scripts/render_shots.py --project PROJECT_DIR --plan shots.json --validate-only`. This checks IDs, source hashes, bounds, style, and the **planned** total frame count. It does not encode or verify the output video's frame count. A too-short source is an error; the tool never silently moves an in-point.
4. Run the same absolute script path without `--validate-only`. It renders clips into `PROJECT_DIR/cache/shots/`, writes `PROJECT_DIR/exports/animation-panel.mp4`, `shot-list.csv`, and `shot-board-manifest.json`, and verifies each encoded clip and the assembled panel have the exact requested frames. Repeated runs reuse hash-verified entries; changing one shot's resolved style changes its cache key.
5. Review a contact sheet and sample cuts, especially at section boundaries or when beat hints conflict with the image. A beat hint is documentation, not proof that a cut is musically right.

Requires Python 3.10+ and FFmpeg/FFprobe with H.264 encoding. The renderer reads existing local sources; it does not distribute or download third-party footage.
