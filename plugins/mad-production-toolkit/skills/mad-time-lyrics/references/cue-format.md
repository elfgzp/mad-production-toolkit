# Cue and style format

`cues.json` is UTF-8 JSON with `duration_seconds`, optional title metadata, and an ordered array of non-overlapping cues:

```json
{
  "duration_seconds": 8.0,
  "title": {"original": "Example Tune", "translation": "示例曲", "artist": "Example Band"},
  "cues": [
    {"start": 1.0, "end": 2.5, "original": "A fictional line", "translation": "一行示例文字"}
  ]
}
```

`start` and `end` are seconds on the **final song timeline**, after any source trimming. Every cue must satisfy `0 <= start < end <= duration_seconds`. Gaps are allowed; overlaps and unordered cues are rejected. Translation may be empty for a single-language project.

`style.json` is required for rendering and must set every field shown in [the first example](../examples/style.json). A [second example](../examples/style-alt.json) shows a distinct 24 fps style. `fps` is a positive rational string, `canvas` is the overlay width and height, and layout fields define anchor, margins, inset, maximum lines, and line gap. The style also sets font paths and sizes, plate color/opacity/radius, and text/highlight/stroke colors. `original_font` and `translation_font` are local paths or `null`; relative paths resolve **beside the style JSON**, independent of the process working directory. `null` uses Pillow's default font for simple Latin previews. Set explicit licensed font paths for Japanese or Chinese. `plate_opacity: 0` removes the backplate.

Three animation objects are required:

| Object | `mode` | `direction` | Other fields |
| --- | --- | --- | --- |
| `highlight` | `none`, `static`, `wipe` | `left-to-right`, `right-to-left`, `top-to-bottom`, `bottom-to-top` | `duration_seconds`, `easing` |
| `entrance`, `exit` | `none`, `fade`, `slide`, `fade-slide` | `up`, `down`, `left`, `right` | `duration_seconds`, `easing`, `distance_pixels` |

`easing` is `linear`, `ease-in`, `ease-out`, or `smoothstep`. Duration `0` makes a mode immediate. A highlight `wipe` finishes after its configured duration from cue start; `static` colors the entire original line. `none` keeps its base color. Motion direction describes actual travel: an entrance marked `up` starts below and moves up into place; an exit marked `up` moves up out of place. `fade` ignores direction and distance. All animation settings are per cue relative to its own start/end. Values in both examples are fictional design choices, not defaults.

The overlay is ProRes 4444 with alpha; set `canvas` to the target panel's exact resolution, not automatically the full video size. Inspect text at cue boundaries and during motion; an off-canvas slide is clipped safely.

`--shift` applies one time offset at export/render time; it is not evidence that every cue is accurate. Keep the approved cue file unchanged and record why the shift was chosen.
