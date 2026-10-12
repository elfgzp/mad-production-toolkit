---
name: mad-mix-audio
description: Use when performance stems have confirmed song-timeline timing and need a repeatable music-video, cover, or MAD mix, balance revision, or lossless audio export.
---

# Mix audio for a MAD

Build a repeatable mix once each stem's song timing is confirmed. Put EQ, gain, pan, short echo reverb, and automation in one JSON config; keep it beside the exported audio. A previously rendered and timeline-aligned NAM, amp, or IR layer can be another input on the same instrument bus. This skill does not run those models. Raw recordings without phrase drift may use the mixer's source trim and timeline placement; those controls do not replace phrase correction by `mad-align-stems`.

If the bass needs a dry/wet modeled chain or dynamics work, read the optional [bass chain notes](references/bass-chain.md) before choosing settings. Any model or IR is a project input with its own license.

1. Confirm each stem's sample content and intended start on the final video timeline. For a full-song FLAC from `mad-align-stems`, use it from sample 0: omit `source_start_sec`, `source_end_sec`, and `timeline_start_sec` (their defaults are 0 or source end). Its original trim, late entrance, and silence are already baked in. If a raw recording has no phrase drift, use [the raw-stem alternative](examples/raw-stems-config.json) to trim and place it once. If phrases drift, correct them in `mad-align-stems` first.
2. Start from [the aligned-stem generic config](examples/generic-config.json) for full-song FLACs, or [the raw-stem alternative](examples/raw-stems-config.json) for recordings that need one-time trim and placement. Replace relative input paths and set the actual duration. Read [the schema](references/config-schema.md) for effect order and units. Begin with conservative levels; balance voices, rhythm, lead, and bass by listening in context.
3. Resolve `mix.py` from this installed skill's `scripts/` directory; run it from any project directory. Check the graph, then render:

   ```bash
   python3 /absolute/path/to/mad-mix-audio/scripts/mix.py mix.json --dry-run
   python3 /absolute/path/to/mad-mix-audio/scripts/mix.py mix.json
   ```

4. Listen around entrances, quiet verses, choruses, solos, and the end. Compare the reference for timing and broad dynamics when supplied; preserve the cover's intended performance and tone. Check channel placement, reverb tails, audible clipping, and final duration. Adjust the JSON and rerun with `--force` only after reviewing the previous version.
5. Keep the config and any pre-rendered wet stems with the project intermediates. The script exports stereo 24-bit FLAC and replaces the destination only after FFmpeg succeeds.

The script needs Python 3.9+ and FFmpeg. The repository contains no recording, model, impulse response, or project-specific settings. Synthetic verification: `python3 -m unittest discover -s tests -v`.
