<p align="center">
  <img alt="Disk Map" src="template.svg" width="480">
</p>

# Disk Map

<p align="center">
  <a href="https://studio.imbue.com/open?git_url=https://github.com/boweiliu/disk-map-template"><img alt="Open in Imbue Studio" height="64" src="https://img.shields.io/badge/Open%20in%20Imbue%20Studio-D8D1C0?style=for-the-badge"></a>
</p>

Didn't work? Create a Studio workspace and paste this to your agent:
` /use-template https://github.com/boweiliu/disk-map-template`

## Why you care

When a workspace disk fills up, "df" says how much is used but not by what, and guessing wastes hours. Disk Map scans the disk once and shows every folder as a block sized by its real footprint, so the thing eating your space is the biggest block on the screen.

## How to use it

Open **Disk Map** from the workspace (it runs on port 8194 and is started by supervisord).

- On first load, with no scan saved, it starts one by itself (about a minute and a half); afterwards it shows the newest saved scan.
- Click a block to see what it is and how big; **Copy path** puts its path on your clipboard. Clicking an entry in the list of biggest items beside the map zooms the map to it.
- **Scan again** takes a fresh scan in the background. Only one scan runs at a time, and the newest 20 are kept.
- `GET /api/scan` returns the newest scan as JSON and `GET /api/scan/raw` the same, pretty-printed; `GET /health` answers `{"status": "ok"}`.

To run it by hand from the workspace root: `uv sync --locked --project system/apps/disk_map`, then `system/apps/disk_map/.venv/bin/disk-map`.

## Ideas for making it yours

- Take a scan every night with a routine that calls `POST /api/rescan`, so there is always a recent one.
- Add a "what grew since the last scan" view; older scans are already kept for it.
- Lower the size thresholds in `scanner.py` (`COLLAPSE_BELOW_BYTES`, `FILE_LEAF_MIN_BYTES`) to show finer detail, or raise them for a lighter page.
- Limit the scan to one folder or leave out mounts you do not care about.
- Mark folders you decided to keep, so a later cleanup does not rediscover them.

## What this is

This repository is a published **Imbue Studio template**: a clean, bootable
snapshot of what an agent built, ready to adapt into your own. It is NOT the
generic workspace template -- it is this specific project.

[`template.md`](template.md) is the full manifest -- what it is, how it
works, what it needs to run, and what to adapt -- with the
machine-readable half (recipe, requirements, and the environment it needs
installed) in [`template.toml`](template.toml).

## License

The Disk Map app (`system/apps/disk_map/`) is licensed **GPL-2.0-only**: it bundles the GPL-2.0-only gp-treemap library
and runs it in the same page. The text is `system/apps/disk_map/LICENSE`; `system/apps/disk_map/NOTICE.md` explains the
scope. The rest of this repository keeps the terms it already carries: see
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and the `LICENSE` files beside individual parts (for example the
shell app's).
