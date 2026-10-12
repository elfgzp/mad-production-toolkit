---
name: mad-align-stems
description: Use when separately recorded cover stems need placement on the song timeline, phrase-level timing review against guide stems, or small reviewed early/late corrections before mixing.
---

# Align cover stems

Use the final song/video timeline as the single clock. Establish each stem's source trim and song-timeline entrance from clear phrase anchors; compare the same instrument in the guide and cover. Read [anchor evidence and JSON schema](references/config-and-anchors.md) before deciding a phrase edit.

The bundled [align.py](scripts/align.py) renders only placement and edits explicitly written in JSON. Resolve its path from this installed skill directory, rather than assuming the project working directory contains a scripts folder. `timeline_start_seconds` delays a whole stem to its song entrance; `trim_seconds` discards source lead-in. A short or late-entering stem needs `pad_to_duration: true` to fill the remaining song timeline with silence. Positive `shift_ms` advances a passage; negative values delay it. Each local edit fades into and out of the shift. Run this before EQ, gain automation, panning, effects, and mixing.

1. Build a config with `duration_seconds`, `output_dir`, and one entry per stem (`id`, `input`, required `trim_seconds`, optional `timeline_start_seconds`, `pad_to_duration`, and `edits`). Use paths relative to the config file or absolute paths. Set `trim_seconds: 0` when no source lead-in should be removed; only `timeline_start_seconds` defaults to 0. Padding defaults to false and must be explicitly enabled for a late entrance or short recording. The output is always a full-length, song-timeline FLAC.
2. Optionally inspect a short guide/cover window with: python3 /absolute/path/to/mad-align-stems/scripts/align.py analyze --config project.json --stem lead --guide guide-lead.wav --guide-trim-seconds 0.4 --start 30 --end 38. This prints candidate attacks and near matches only; it never changes audio or adds edits.
3. Confirm phrase identity, shared attacks, opening/ending anchors, and quiet fade locations by listening and waveform/spectrogram inspection. Do not use a single cross-correlation or onset peak as an edit instruction. If the notes differ, keep the stem untouched.
4. Add only justified edits to JSON, using song-timeline seconds within the source's active interval; never put an edit in padded silence. Run python3 /absolute/path/to/mad-align-stems/scripts/align.py render --config project.json; add --overwrite only to replace an existing render. Outputs are 48 kHz 24-bit FLAC plus alignment_audit.json.
5. Compare each corrected phrase and its transitions by listening. Use analyze --rendered against the guide if useful; verify the intended entrance, padded silence, unchanged anchors, exact full-song sample count, and musically acceptable remaining differences. Pass the rendered FLAC to `mad-mix-audio` without a second source trim or timeline delay.

Requires Python 3.10+, NumPy, FFmpeg, and FFprobe. The script preserves each source's mono/stereo/multichannel count (up to eight channels) and rejects out-of-range reads, edits outside recorded audio, overlapping edits, missing sources, and accidental overwrite. It does not alter source files. It does not download guide audio or imply permission to redistribute it.
