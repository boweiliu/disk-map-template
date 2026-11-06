# disk-map

Interactive treemap of where every gigabyte on the workspace disk goes, from a saved disk scan.

A scan walks every disk-backed mount (real on-disk bytes, hard links counted once, symlinks not followed, never crossing
into another mount) and is saved as gzipped JSON. The page draws the newest scan as an explorable treemap with the
bundled gp-treemap library; older scans are kept for comparison.

## Run

The app runs as a window inside an Imbue Studio workspace; its supervisord program starts it. To run it by hand from the
workspace root:

```
uv sync --locked --project system/apps/disk_map
system/apps/disk_map/.venv/bin/disk-map
```

- Port: `DISK_MAP_PORT` (default `8194`), bound on `127.0.0.1`.
- Data folder: `DISK_MAP_DATA_DIR` (default `data/.apps/disk-map`). Saved scans are `scans/scan-<unix time>.json.gz`;
  the newest 20 are kept. These are the raw records the page is drawn from.
- Routes: `/` (the page), `/api/scan` and `/api/scan/raw` (latest scan), `GET`/`POST /api/rescan` (status / start a new
  scan in its own process), `/api/schema` (API document), `/health`, `/assets/<name>`, `/_static/<name>` (the shell's
  browser modules).

## Test

`src/disk_map/runner_test.py` checks the API document against the manifest; `test_disk_map_ratchets.py` holds the
workspace's standard code-quality ratchets, including the type check with `ty`. Run
`uv run --project system/apps/disk_map pytest` from the workspace root.

## License

GPL-2.0-only; the text is in `LICENSE` and the reasoning in `NOTICE.md`. The page draws its map with gp-treemap
(`@imbue-ai/gp-treemap` 0.6.2, GPL-2.0-only, derived from GrandPerspective by Erwin Bonsma), bundled unmodified in
`src/disk_map/assets/gp-treemap.bundle.js`, so the whole app is distributed under the same terms.
