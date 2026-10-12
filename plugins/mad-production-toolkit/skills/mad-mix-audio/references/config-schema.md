# Mix config v1

`scripts/mix.py` reads UTF-8 JSON. Paths in `output` and `stems[].path` are relative to the **config file**; `--output` is relative to the current shell directory. Inputs must exist; output must end in `.flac`. Existing output requires `--force`. Use `--dry-run` to validate and print the FFmpeg command without writing audio.

## Choosing the input stage

For a FLAC rendered by `mad-align-stems`, use its full-song output directly and omit `source_start_sec`, `source_end_sec`, and `timeline_start_sec`. That FLAC already begins at song time 0, includes the approved source trim and any delayed entrance or padded silence, and has the requested final sample count. Applying the raw-source controls again discards or shifts approved audio. [The generic config](../examples/generic-config.json) demonstrates this path.

Only for a raw recording that does not need phrase correction, set `source_start_sec` to skip lead-in and `timeline_start_sec` to choose its song entrance. [The raw-stem alternative](../examples/raw-stems-config.json) demonstrates this path. A single project can contain both kinds of input, but classify each stem explicitly before filling these fields; keep source-to-song timing evidence with the project.

## Top-level fields

| Field | Meaning |
| --- | --- |
| `version` | Required integer `1`. |
| `duration_sec` | Required final mix length; every stem is padded or cut to this timeline. |
| `sample_rate` | Output sample rate in Hz; defaults to 48000. |
| `output` | Required `.flac` path. Export is stereo, FLAC codec, 24-bit integer samples. |
| `stems` | Nonempty array of input objects. Names must be unique. |
| `buses` | Optional object keyed by bus name. Each bus sums its stems before effects. |
| `master` | Optional final gain and limiter. No limiter is inserted by default. |

## Stem fields

`name` and `path` are required. `bus` defaults to `main`. These are the optional fields:

| Field | Meaning |
| --- | --- |
| `source_start_sec`, `source_end_sec` | Trim positions in the source file. End is exclusive and must exceed start. Defaults: 0 and source end. |
| `timeline_start_sec` | Place the trimmed stem on the final timeline; defaults to 0. Delay is rounded to the nearest millisecond. |
| `placement` | `mono` (default) downmixes to one signal then pans with constant power; `stereo` keeps channel separation and adjusts balance. |
| `pan` | From -1 (left) to +1 (right), default 0. With `stereo`, opposite-side channel gain is reduced. |
| `highpass_hz`, `lowpass_hz` | Optional cut frequencies. |
| `eq` | Array of bands: `{ "type": "peak" | "low_shelf" | "high_shelf", "frequency_hz": number, "width": number, "gain_db": number }`. `width` is Q for peak and shelf slope for shelves; default 1. |
| `gain_db` | Static gain before reverb and pan. Defaults to 0 dB. |
| `reverb` | Short echo taps: `{ "delay_ms": [38, 71], "decay": [0.25, 0.12], "wet": 0.2 }`. Arrays must match. `wet` scales tap strengths while leaving direct gain at unity. This is an echo approximation, not convolution. |
| `automation` | Gain keyframes, e.g. `[{"time_sec":0,"gain_db":0},{"time_sec":20,"gain_db":2}]`. Times are on the **final mix timeline**. Gain interpolates linearly in dB, staying at the first or last value outside the keyframe range. |

## Bus and master effects

Each bus supports the same highpass, lowpass, EQ, gain, reverb, and automation fields. It can also contain `compressor`: `threshold_db` (required, dBFS), `ratio` (required), and optional `attack_ms` (default 20), `release_ms` (200), `knee` (2), `detection` (`rms` or `peak`, default `rms`), `makeup_db` (0). Use the **same bass bus** for dry bass and any already rendered amp/NAM/IR layer when they should share compression and fader rides. Set relative dry/wet balance with their stem gains.

`master` supports `gain_db` and optional `limiter`: `{ "limit_db": -1, "attack_ms": 5, "release_ms": 50 }`. A limiter ceiling prevents sample overs but does not replace a listening or loudness review. Master gain comes before limiter.

Processing order: source trim → resample/stereo format → stem highpass/lowpass/EQ/gain/reverb/pan → timeline placement and length clamp → stem automation → bus sum and effects (compressor before automation) → master sum/gain/limiter → 24-bit FLAC. The script does not time-stretch or repair misplayed phrases. It deliberately leaves compression, limiting, loudness targets, and the chosen sound to the producer.
