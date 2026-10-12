# MAD Production Toolkit

[简体中文](README.md) | **English**

A reusable Codex skill suite for music video and cover MAD production. It turns a local collection of authorized media into a traceable shot plan, aligned and mixed audio, timed lyrics, a composited video, and a checked delivery bundle.

**Choose the presentation and mix for each project.** Fonts, sizes, colors, placement, title wording, fades, panel geometry, EQ, gain, pan, and effects are configurable inputs. The JSON examples are fictional demonstrations, not a toolkit look or sound.

## Skills

| Skill | Use it for |
| --- | --- |
| `mad-source-assets` | Record source, rights status, metadata, hashes, and local project copies. |
| `mad-plan-shots` | Plan beat-aware animation or performer-camera cuts into an exact-frame panel and edit manifest. |
| `mad-align-stems` | Compare performance phrases to guide stems and apply reviewed local timing edits. |
| `mad-time-lyrics` | Check cue coverage, export subtitles, and render configurable bilingual lyric motion. |
| `mad-mix-audio` | Mix aligned stems with automation, EQ, stereo placement, bass compression, and wet layers. |
| `mad-edit-video` | Build and cache performer/animation panels; render cards, overlays, and audio revisions. |
| `mad-deliver-project` | Verify the result and create a project manifest and checked video/audio archive. |

Read the relevant `SKILL.md` in [`plugins/mad-production-toolkit/skills`](plugins/mad-production-toolkit/skills) before running its script. The [end-to-end workflow](docs/workflow.md) covers the project handoffs, optional bass processing, revision strategy, and review points. Repeat a stage when review finds a timing, mix, or layout issue; keep the source files and configuration alongside your project.

## Install in Codex

```bash
codex plugin marketplace add elfgzp/mad-production-toolkit
PLUGIN_ROOT="$(codex plugin add mad-production-toolkit@mad-production-toolkit --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["installedPath"])')"
python3 -m pip install -r "$PLUGIN_ROOT/requirements.txt"
```

`PLUGIN_ROOT` comes from the install result's `installedPath` and points to the cached plugin containing the requirements file and skill scripts. Install dependencies with the same `python3` interpreter used to run the skill scripts. If you use a virtual environment, run the scripts with that environment's Python. For a direct repository clone, install dependencies from the plugin directory instead:

```bash
git clone https://github.com/elfgzp/mad-production-toolkit.git
python3 -m pip install -r mad-production-toolkit/plugins/mad-production-toolkit/requirements.txt
```

The GitHub repository is a Codex marketplace source. Start a new Codex conversation after installation to use the skills. Listing in OpenAI's public Plugins Directory is a separate submission and review process.

## Requirements

- Python 3.10 or newer; `numpy` and `Pillow` for the audio analysis and text rendering tools.
- FFmpeg and FFprobe available on `PATH`, with the `libx264`, `prores_ks`, AAC, and FLAC encoders.
- Local inputs that you are permitted to edit, display, and distribute for the intended use. This repository contains no project footage, recordings, lyrics, translations, logos, fonts, NAM models, or impulse responses.

Run `ffmpeg -hide_banner -encoders | grep -E 'libx264|prores_ks|[[:space:]]aac[[:space:]]|[[:space:]]flac[[:space:]]'` and confirm that all four encoders appear. See each skill for its CLI and config format. All scripts operate on explicit local paths and do not call a hosted media service.

## Development and validation

```bash
python3 scripts/validate_all.py
```

Run validation from the repository root. Tests generate short synthetic media in temporary directories and need no project footage. The script checks the basic structure of all seven skills, names, versions, and icon paths in both manifests, and local documentation links, then runs skill unit tests and a synthetic end-to-end test. It does not perform full JSON Schema validation of the manifests. For publication, also review the staged Git files for private paths, secret material, and third-party media.

## Licensing and data

Original toolkit code and documentation are MIT licensed. This license does not cover any media you supply. See [PRIVACY.md](PRIVACY.md) for local processing and [CONTRIBUTING.md](CONTRIBUTING.md) for contribution rules.
