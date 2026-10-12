# MAD Production Toolkit

A reusable Codex skill suite for music video and cover MAD production. It turns a local collection of authorized media into a traceable shot plan, aligned and mixed audio, timed lyrics, a composited video, and a checked delivery bundle.

**Choose the presentation and mix for each project.** Fonts, sizes, colors, placement, title wording, fades, panel geometry, EQ, gain, pan, and effects are configurable inputs. The JSON examples are fictional demonstrations, not a toolkit look or sound.

## Skills

| Skill | Use it for |
| --- | --- |
| `mad-source-assets` | Record source, rights status, metadata, hashes, and local project copies. |
| `mad-plan-shots` | Turn a beat-aware shot plan into an exact-frame animation panel and edit manifest. |
| `mad-align-stems` | Compare performance phrases to guide stems and apply reviewed local timing edits. |
| `mad-time-lyrics` | Check cue coverage, export subtitles, and render configurable bilingual lyric motion. |
| `mad-mix-audio` | Mix aligned stems with automation, EQ, stereo placement, bass compression, and wet layers. |
| `mad-edit-video` | Build and cache performer/animation panels; render cards, overlays, and audio revisions. |
| `mad-deliver-project` | Verify the result and create a project manifest and checked video/audio archive. |

Read the relevant `SKILL.md` in [`plugins/mad-production-toolkit/skills`](plugins/mad-production-toolkit/skills) before running its script. The [end-to-end workflow](docs/workflow.md) covers the project handoffs, optional bass processing, revision strategy, and review points. Repeat a stage when review finds a timing, mix, or layout issue; keep the source files and configuration alongside your project.

## Install in Codex

```bash
codex plugin marketplace add elfgzp/mad-production-toolkit
codex plugin add mad-production-toolkit@mad-production-toolkit
```

The GitHub repository is a Codex marketplace source. Listing in OpenAI's public Plugins Directory is a separate submission and review process.

## Requirements

- Python 3.10 or newer; `numpy` and `Pillow` for the audio analysis and text rendering tools.
- FFmpeg and FFprobe available on `PATH`, with H.264, AAC, FLAC, and ProRes encoders.
- Local inputs that you are permitted to edit, display, and distribute for the intended use. The toolkit does not include or acquire copyrighted video, recordings, lyrics, translations, logos, fonts, NAM models, or impulse responses.

Install Python dependencies with `python3 -m pip install -r requirements.txt`. See each skill for its CLI and config format. All scripts operate on explicit local paths and do not call a hosted media service.

## Development and validation

```bash
python3 scripts/validate_all.py
```

Tests generate short synthetic media in temporary directories. The validation script checks every skill and both plugin manifests; it does not need project footage. For publication, also review the staged Git files for private paths, secret material, and third-party media.

## Licensing and data

Original toolkit code and documentation are MIT licensed. This license does not cover any media you supply. See [PRIVACY.md](PRIVACY.md) for local processing and [CONTRIBUTING.md](CONTRIBUTING.md) for contribution rules.
