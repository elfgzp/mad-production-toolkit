---
name: mad-source-assets
description: Inventory and ingest locally supplied media for a MAD project with provenance, rights status, ffprobe metadata, and a portable SHA-256 manifest. Use before editing; this skill does not download media or decide licensing.
---

# MAD source assets

Use this skill when source videos, performances, reference tracks, graphics, or subtitle inputs need a traceable local inventory. Ask for missing source or permission details instead of inventing them. Public availability does not establish reuse rights.

1. Find candidate material from the user's files or relevant creator, publisher, and licensed-library sources. Record the source page, author, reuse terms, and access date in private project notes. Download or export only material the project is allowed to use; follow the source's permitted method. The script starts once a local copy exists.
2. Record one stable asset ID, local input path, origin, creator, and rights status per asset. Use `review-needed` when permission is uncertain. For a `public_url` origin, provide a credential-free HTTP(S) URL with no query or fragment; keep signed download URLs out of the manifest. The [configuration schema](references/assets.schema.json) and [fictional example](references/assets.example.json) show the format.
3. Run `python3 <skill-directory>/scripts/ingest_assets.py --config assets.json --project PROJECT_DIR`, replacing `<skill-directory>` with this skill's absolute directory. The script copies files to `PROJECT_DIR/assets/`, probes media streams, and writes `PROJECT_DIR/assets-manifest.json`. It never downloads source material.
4. Review the manifest and resolve `review-needed` entries before publication. Keep the source configuration local when it contains private paths. The manifest stores only project-relative asset paths and a controlled origin reference, never the source filesystem path.
5. Treat the manifest hash as the source identity for shot rendering and downstream caches. A changed file under the same ID fails ingest; assign a new ID or explicitly remove the old project copy after reviewing dependents.

Requires Python 3.10+ and FFmpeg/FFprobe. `--help` lists CLI options. The manifest is a technical record, not a license grant. Keep third-party binaries and original performance recordings out of a public skill repository.
