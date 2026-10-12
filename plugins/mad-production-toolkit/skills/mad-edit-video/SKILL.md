---
name: mad-edit-video
description: Use when assembling local performance cameras or a planned clip sequence into a music MAD with timed panels, color matching, title layers, or reusable render caches.
---

# Edit and composite MAD video

Use local footage the project is authorized to edit. Keep the video sync offsets independent from audio stem trims: camera recorders and audio takes often have different lead-in times.

1. Probe source resolution, frame rate, and duration. Compare a clear hand movement or embedded camera audio with the final song timeline; record the chosen video trim and evidence for each camera. Treat weak visual matches as provisional.
2. Plan the layout in [the base config](references/video-config.md). Set each panel's crop, position, color correction, background color, and fade times explicitly. Pick a common entrance and exit for related performer panels. One base config accepts at most eight panel sources. For more than eight **sequential cuts inside one panel**, first use `mad-plan-shots` to render those performer takes as a single frame-accurate montage; its `exports/animation-panel.mp4` is a video input despite the filename. Match that montage's frame rate, dimensions, and total frames to the receiving panel and song. Render the **textless base** with `video.py base --config base.json --output base.mp4`. Its input/config/FFmpeg fingerprint is cached; a valid rerun skips processing.
3. Build title, performer labels, and outro from declarative [card configs](references/card-config.md) with `card.py`. Fonts, sizes, colors, positions, spacing, logo paths, background, motion, and fade timing belong to the project config. Review the result at playback size; close elements and canvas overflow are rejected.
4. Place title and lyric alpha layers over the cached base using `video.py overlay --config layers.json --output song.mp4`. Rendered lyric layers should match their target panel size and be positioned at that panel's origin. Layer size, opacity, and appearance time can be set independently. Add the selected mix with `--audio mix.flac`.
5. If only the mix changes, use `video.py remux --video song.mp4 --audio revised.flac --output revised.mp4` to copy the video bitstream. Check stream hash, full decode, duration, and sync before delivery.

Resolve `video.py` and `card.py` from this installed skill's `scripts/` directory; the project working directory need not contain them. The example layouts and visual values are fictional demonstration data, not a house style. Use the user's song, footage, and design direction to choose them. The scripts require FFmpeg/FFprobe; `card.py` also requires Pillow. See [base example](examples/base.json), [overlay example](examples/layers.json), and [title example](examples/title.json).
