---
name: mad-deliver-project
description: Finish a local MAD project with frame-checked outro assembly, full media decode and loudness QA, an explicitly authorized asset bundle, and a verified video-plus-audio ZIP. Use at delivery, after picture and mix are ready.
---

# MAD project delivery

Keep the final picture, lossless mix, editable intermediates, and release package distinct. Locate this installed skill's absolute directory, then run `python3 <skill-directory>/scripts/deliver.py --help`; use that absolute script path for every command below.

1. `append-outro --song-video SONG.mp4 --outro-video CARD.mp4 --mix-audio MIX.flac --output FINAL.mp4` joins the two pictures at the song's frame boundary. The song picture must have a constant frame rate. The mix must cover the whole song; the tool rejects a short mix and trims at the song boundary before padding silence over the card. The default maximum excess mix duration is 0.02 seconds (`--mix-tolerance`). It normalizes the card to the song's frame rate and size, then verifies total frames.
2. `qa --video FINAL.mp4 --expect-frames N --report qa.json` checks the expected frame count, stream durations, complete decoding, integrated loudness, and true peak. It accepts exactly one video and at most one audio stream; a silent card needs `--allow-silent`. The default audio/video stream duration tolerance is 0.05 seconds (`--av-tolerance`) to accommodate encoder padding. Review the report and watch representative cuts and lyric/title frames; numeric checks do not replace viewing.
3. `bundle --config bundle.json --output-dir PROJECT_BUNDLE` copies only the listed assets. Each item needs a declared rights status and a permission reference; the tool checks these fields but cannot verify the underlying permission. Use the [schema](references/bundle.schema.json) and [fictional example](references/bundle.example.json). The resulting manifest has relative paths and SHA-256, with no original local paths. The output directory must contain only listed files, their parent directories, and the generated manifest. Do not include an asset whose reuse or redistribution has not been confirmed for the intended delivery.
4. `zip --video FINAL.mp4 --audio MIX.flac --output DELIVERY.zip` packages exactly those two files and verifies archive CRC plus each member's SHA-256. These checks establish file integrity, not mix alignment, decodability, or redistribution rights; run QA and review the bundle separately before publishing.

The tool reads local media only. It does not infer license permission from public availability, retrieve footage, choose visual design, or silently alter an existing bundle asset. Requires Python 3.10+ and FFmpeg/FFprobe with H.264 encoding.
