# Timeline, configuration, and evidence

## JSON configuration

All edit times are seconds on the output song/video timeline. The source file is decoded to PCM at 48 kHz first. For a stem with `trim_seconds = 0.1` and `timeline_start_seconds = 0`, output time 0 reads source time 0.1. With `timeline_start_seconds = 40`, output time 40 reads source time 0.1 and the preceding 40 seconds are silent. An edit with `shift_ms = 20` reads 20 ms later in the source during its full-shift region, so that region is heard 20 ms earlier in the output. A negative value delays the region. The fades blend back to the placed source timing.

Paths are absolute or relative to the JSON file; only output files under output_dir are written. output_dir itself may also be relative to the config file.

    {
      "duration_seconds": 120.0,
      "output_dir": "./aligned",
      "stems": [
        {
          "id": "lead",
          "input": "./inputs/lead.wav",
          "trim_seconds": 0.1,
          "edits": [
            {
              "fade_in": [24.50, 24.58],
              "fade_out": [28.85, 28.94],
              "shift_ms": 20
            }
          ]
        },
        {
          "id": "bass",
          "input": "./inputs/bass.wav",
          "trim_seconds": 0.14,
          "edits": []
        },
        {
          "id": "solo",
          "input": "./inputs/solo.wav",
          "trim_seconds": 0.05,
          "timeline_start_seconds": 80.0,
          "pad_to_duration": true,
          "edits": []
        }
      ]
    }

`timeline_start_seconds` defaults to 0 and must precede `duration_seconds`. `pad_to_duration` defaults to false; set it to true when placing a stem after song time 0 or when the recording ends before the full song timeline. Padding adds silence before the entrance and after the available source. Without explicit padding, a short source is rejected. For each edit, require `0 <= fade_in[0] < fade_in[1] < fade_out[0] < fade_out[1] <= duration_seconds`, with the entire window inside recorded audio after placement; edits on the same stem may not overlap. The shift must be nonzero after rounding to samples, and the source must contain every shifted read. Stem IDs use lowercase letters, digits, underscores, and hyphens, beginning with a letter.

Outputs are `<id>_aligned_24bit.flac` plus `alignment_audit.json` in `output_dir`. Every FLAC starts at song time 0 and has `round(duration_seconds * 48000)` samples, including any requested silence. The audit records source and output SHA-256, placement and padding, the active-source endpoint, edit windows, shift samples, unedited intervals, and a pre-encode check that samples outside all edit windows are unchanged.

## Evidence for an edit

1. Common timeline: Work from decoded PCM. State guide and cover source trims and timeline entrances, then convert all observed attack times to output timeline. Do not mix source-file seconds and finished-video seconds.
2. Phrase identity: Confirm the same instrument and at least roughly the same notes/phrase. Different arrangement, distortion, octave, or deliberate variation can defeat waveform matching.
3. Outer anchors: Find a clear attack or boundary just before and just after the suspected drift. If both are already close, preserve them and correct only the interior. If the ending anchor drifts as well, revisit global trim or tempo rather than inserting a local patch.
4. Interior pattern: Seek several common attacks with a consistent signed offset; inspect one or more independent cues (spectrogram/pitch content, low-frequency energy, rhythm grid, or a second set of attacks). One late pluck is not enough. A strong reference phrase may be silent in the cover or vice versa; that is not timing evidence.
5. Alias check: Repeated eighth/sixteenth notes can create false peaks one subdivision away. A large cross-correlation maximum is a candidate, never an automatic trim. Confirm named attacks and phrase endpoints individually.
6. Fade placement: Put fade in/out in low-energy gaps or between attacks. Avoid doubling a sustained chord, hiding a pick attack, or crossing a different note. Listen to each transition and the next phrase.
7. Negative controls: Recheck known aligned opening/ending phrases and any strong anchor outside each edit. The edit should improve the target phrase without moving those controls.

The analyze command is read-only and deliberately conservative. It uses spectral-flux peaks at 10 ms hops, then pairs nearby candidates inside a requested window. Positive stem_minus_guide_ms means the cover is later. Its median and quartiles are candidate statistics, not a final edit amount. Different timbres, performance choices, reverb, and repeated notes can move or alias these estimates. Inspect a short phrase and listen before changing JSON.

## Verification

- Decode each output fully; verify 48 kHz, 24-bit FLAC, expected channel count, and round(duration_seconds * 48000) samples.
- Compare the placed source, including intentional silence, with the result outside edit windows. Exact PCM equality is guaranteed before FLAC encoding; after 24-bit quantization allow a tiny numerical tolerance.
- Check the same guide/cover attacks before and after correction in the target phrase, plus outer anchors and unaffected sections.
- Keep the original stem and the JSON/audit so the change can be reversed or revised.
