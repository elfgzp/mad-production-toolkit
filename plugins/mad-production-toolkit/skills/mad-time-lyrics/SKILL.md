---
name: mad-time-lyrics
description: Time, verify, translate, and render lyrics for a music video or MAD when cue coverage, bilingual subtitles, or animated on-screen text needs careful alignment.
---

# Time and render lyrics

Work from lyrics the user is authorized to use. Keep source text, translations, title provenance, and timing evidence in the project directory; never commit a real song's lyric text to a reusable skill repository.

1. Confirm the target audio duration and identify the vocal entrances, rests, and repeated phrases. A public LRC or ASR result is a starting hypothesis; listen and compare against the actual cover audio. A single global shift is appropriate only if the entire song has a consistent offset. Check the first verse, choruses, sparse sections, and final line for missing cues.
2. Record every cue as `start`, `end`, `original`, and optional `translation` in [the cue format](references/cue-format.md). Keep the original title as the primary title when a distributor has not published a translated title; do not present an interpretation as an official title. If the user chooses a translated subtitle, keep that designation in project notes, not necessarily on screen.
3. Locate this installed skill directory and invoke its `scripts/lyrics.py` by **absolute path**, regardless of the project working directory. Run `validate --cues cues.json`, then `export --cues cues.json --output-dir subtitles/` for SRT/LRC. Use `--shift` only after confirming a common offset from the actual audio.
4. For animated lyrics, define every visual parameter in a project-specific style JSON, then run `render --cues cues.json --style style.json --output lyrics.mov`. Choose fonts, sizes, colors, position, plate opacity, and separate highlight/entrance/exit modes, directions, durations, and easing for the actual footage and song. Relative font paths resolve beside `style.json`; verify legibility on the moving background. Pick fonts that cover both scripts and are licensed for the intended output.
5. Composite the overlay at the panel origin. Inspect contact frames at phrase starts, long lines, line ends, and the last cue. Confirm exact frame count, alpha channel, and no text outside the safe area.

The renderer requires a local JSON style file and refuses to overwrite outputs without `--force`. It uses Pillow and FFmpeg; no network service or hosted model is required. See [fictional cues](examples/cues.json), two [contrasting](examples/style.json) [visual styles](examples/style-alt.json), and the [style reference](references/cue-format.md). Example colors and motion are demonstrations, not a house style.
