# Title, performer-credit, and outro card config

`scripts/card.py` takes a JSON object with `canvas`, `background` (`transparent`, `solid`, or `gradient`), `min_gap`, and `elements`. For video output also set `fps`, `duration_seconds`, `fade_in_seconds`, `fade_out_seconds`, and `fade_easing` (`linear` or `smoothstep`). Opaque video also needs `fade_color`. Transparent video produces an alpha MOV; an opaque card produces MP4. A `.png` output is a static layer and needs no duration.

Each element specifies `type: text|image`, `x` and `y`, and `align: center|left|right`. `y` is the vertical center; `x` is the center or the corresponding left/right edge. Text requires `text`, `size`, and `color`; set `font` to a suitable local font path for the languages used, plus optional `stroke_width` and `stroke_color`. Images require local `path`, optional `max_width` and `max_height`. The script checks canvas overflow and element spacing; use `allow_overlap: true` on a particular element only when intentional.

For video, an optional per-element `motion` object controls `start_seconds`, `end_seconds`, `fade_in_seconds`, `fade_out_seconds`, `offset_from: [dx,dy]`, `offset_to: [dx,dy]`, `scale_from`, `scale_to`, `opacity`, and `easing`. Unspecified motion values are neutral (full-card duration, no offset or scale change, full opacity). Motion that moves an element beyond the canvas is rejected. Static PNG cards do not accept `motion`.

All visual choices come from the project config. The [fictional title example](../examples/title.json) uses a text mark rather than a copyrighted band logo. For a cover, include an explicit cover label such as `BAND COVER` in the content, with copy chosen by the user. Do not infer permission to redistribute a third-party logo from the fact that it appears on an official website.

Use a PNG for persistent performer names, or a MOV for names that fade in/out. Put the closing message in its own opaque card when the song should finish before the silent outro. Verify that the text is separated from the logo and legible at the target resolution.
