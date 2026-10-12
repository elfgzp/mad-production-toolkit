# End-to-end workflow

This is a project template, not a fixed aesthetic or mix preset. Choose the frame rate, canvas, typography, color, layout, gain, effects, and loudness target for the particular song and publication destination.

## 1. Scope and source

Create a private project directory with `sources/`, `configs/`, `cache/`, `exports/`, and `delivery/`. Confirm the intended final audio or video as the timeline clock before cutting footage. Search for footage, artwork, lyric sources, and reference stems as needed; prefer creator or publisher sources and preserve the page URL, creator, terms, and access date in private notes. A discoverable page is not automatically a license. Acquire only media the project is allowed to use, then inventory local copies with `mad-source-assets`.

Record IDs and hashes so later substitutions are explicit. Keep downloaded files and source URLs containing access credentials outside the shared repository. The ingest script begins with local files, because retrieval rules vary by source.

## 2. Story and performance timing

Map verses, choruses, solos, transitions, and outro to musical time. For animation material, use `mad-plan-shots` to write source in-points and exact frame counts, validate source bounds, then render a cached animation panel. Review actual cuts while listening: a beat marker suggests a cut but cannot determine the story.

For performance cameras, note trim points independently of their recorded audio. Align a visible pick strike or other clear action to the final mix clock. Compare camera color and entrance/exit behavior in the actual composition; encode crop, color, fade, and placement in `mad-edit-video` configuration. If a supplied replacement camera already has a preferred grade, preserve it by choosing the project correction accordingly.

## 3. Stem alignment and mix

If a guide or original multitrack is available, compare the same instrument with the cover stem. First establish opening and ending anchors. A phrase may differ musically, so require phrase identity and several recognizable attacks before cutting. Use `mad-align-stems` for explicit local edits with quiet crossfade regions. Check the corrected audio on both sides of each splice and ensure unchanged sections still align.

Mix only the aligned stems. `mad-mix-audio` accepts per-instrument EQ, gain and section automation, stereo placement, reverb or wet layers, and bass compression. Match levels in context, including when vocals enter; compare a reference for timing and broad balance without copying its waveform. A NAM amp/cab capture, impulse response, or DAW-rendered bass layer can be supplied as an additional local stem when licensed and level matched. [Bass chain notes](../plugins/mad-production-toolkit/skills/mad-mix-audio/references/bass-chain.md) cover that optional branch.

When a requested revision changes only the sound, render a new lossless audio version and use `mad-edit-video remux` to preserve the video stream. Keep named revisions and their configs so a listening comparison can be reproduced.

## 4. Lyrics, titles, and video

Time lyrics against the actual final audio. Verify the first verse, every repeated section, the final line, and gaps; a global subtitle offset works only when the error is consistent. Store source, translation, and translated-title provenance privately. Use `mad-time-lyrics` to validate/export cues and create a transparent animated overlay from a project style config.

Use `mad-edit-video` to render the textless base once, then composite cards, musician labels, lyric overlays, and soundtrack. Set all title and outro text, logos, fonts, sizes, colors, positions, transparency, and fade timing in project configuration. For a cover, make the cover credit clear in the chosen title wording. Check title and lyric readability over representative moving frames. Compose the outro after the song only when the intended final timeline includes it.

## 5. Technical and human review

Use `mad-deliver-project` for stream metadata, full decode, duration/frame checks, and archive integrity. Then watch and listen to the full result at normal playback size and level. Spot-check early and late phrases, musician synchronization, subtitles, color matching, stereo balance, vocal masking, transient harshness, bass audibility, reverb tails, and closing credits. Technical checks cannot decide whether a performance or translation feels right.

Freeze the chosen video and audio files, record hashes in the delivery manifest, and package only the files the recipient needs. Keep intermediate renders and full source files in the private project cache, not in this toolkit repository.
