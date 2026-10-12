---
name: mad-align-stems
description: Use when separately recorded cover stems need song-timeline trimming, phrase-level timing review against guide stems, or small reviewed early/late corrections before mixing.
---

# Align cover stems

Use the final song/video timeline as the single clock. Establish each stem's global trim from clear opening and ending phrase anchors; compare the same instrument in the guide and cover. Read [anchor evidence and JSON schema](references/config-and-anchors.md) before deciding a phrase edit.

The bundled [align.py](scripts/align.py) renders only edits explicitly written in JSON. Resolve its path from this installed skill directory, rather than assuming the project working directory contains a scripts folder. Positive shift_ms advances the passage; negative values delay it. Each edit has a fade in, an interior full-shift region, and a fade out that returns to the original timing. Other samples and the final duration stay fixed. Run it before EQ, gain automation, panning, effects, and mixing.

1. Build a config with duration_seconds, output_dir, and one entry per stem (id, input, trim_seconds, optional edits). Use paths relative to the config file or absolute paths.
2. Optionally inspect a short guide/cover window with: python3 /absolute/path/to/mad-align-stems/scripts/align.py analyze --config project.json --stem lead --guide guide-lead.wav --guide-trim-seconds 0.4 --start 30 --end 38. This prints candidate attacks and near matches only; it never changes audio or adds edits.
3. Confirm phrase identity, shared attacks, opening/ending anchors, and quiet fade locations by listening and waveform/spectrogram inspection. Do not use a single cross-correlation or onset peak as an edit instruction. If the notes differ, keep the stem untouched.
4. Add only justified edits to JSON. Run python3 /absolute/path/to/mad-align-stems/scripts/align.py render --config project.json; add --overwrite only to replace an existing render. Outputs are 48 kHz 24-bit FLAC plus alignment_audit.json.
5. Compare each corrected phrase and its transitions by listening. Use analyze --rendered against the guide if useful; verify unchanged anchors, exact sample count, and that remaining timing differences are musically acceptable.

Requires Python 3.10+, NumPy, FFmpeg, and FFprobe. The script preserves each source's mono/stereo/multichannel count (up to eight channels) and rejects out-of-range reads, overlapping edits, missing sources, and accidental overwrite. It does not alter source files. It does not download guide audio or imply permission to redistribute it.
