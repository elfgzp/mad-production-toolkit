---
name: mad-mix-audio
description: Use when aligning and mixing separate performance stems for a music video, cover, or MAD, including per-instrument EQ, stereo placement, gain rides, bass compression, and 24-bit FLAC export.
---

# Mix audio for a MAD

Build a repeatable mix from **already aligned** stems. Put timing offsets, EQ, gain, pan, short echo reverb, and automation in one JSON config; keep it beside the exported audio. A previously rendered NAM, amp, or IR layer can be another input on the same instrument bus. This skill does not run those models.

If the bass needs a dry/wet modeled chain or dynamics work, read the optional [bass chain notes](references/bass-chain.md) before choosing settings. Any model or IR is a project input with its own license.

1. Confirm each stem's sample content and its intended start on the final video timeline. Use source trim for leading silence and timeline start for placement. If performances drift within a song, fix those edits before mixing.
2. Copy [the generic config](examples/generic-config.json), replace its relative input paths and set the actual duration. Read [the schema](references/config-schema.md) for effect order and units. Begin with conservative levels; balance voices, rhythm, lead, and bass by listening in context.
3. Resolve `mix.py` from this installed skill's `scripts/` directory; run it from any project directory. Check the graph, then render:

   ```bash
   python3 /absolute/path/to/mad-mix-audio/scripts/mix.py mix.json --dry-run
   python3 /absolute/path/to/mad-mix-audio/scripts/mix.py mix.json
   ```

4. Listen around entrances, quiet verses, choruses, solos, and the end. Compare the reference for timing and broad dynamics when supplied; preserve the cover's intended performance and tone. Check channel placement, reverb tails, audible clipping, and final duration. Adjust the JSON and rerun with `--force` only after reviewing the previous version.
5. Keep the config and any pre-rendered wet stems with the project intermediates. The script exports stereo 24-bit FLAC and replaces the destination only after FFmpeg succeeds.

The script needs Python 3.9+ and FFmpeg. The repository contains no recording, model, impulse response, or project-specific settings. Synthetic verification: `python3 -m unittest discover -s tests -v`.
