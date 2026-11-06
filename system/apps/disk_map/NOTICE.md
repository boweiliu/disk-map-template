# Disk Map: licensing

Disk Map is licensed under the **GNU General Public License, version 2 only** (SPDX: `GPL-2.0-only`). The full text is
in [`LICENSE`](LICENSE).

## Why GPL

The page draws its map with **gp-treemap**, which is GPL-2.0-only:

- `src/disk_map/assets/gp-treemap.bundle.js` is gp-treemap 0.6.2, unmodified: it is byte for byte the package's
  `dist/gp-treemap.bundle.js` (sha256 `402582192d8f3d7261f327f4b404adfb6ff2085fd0e553b8a0e8cdc47d1e3398`). It is
  published as `@imbue-ai/gp-treemap` on npm, its source is at <https://github.com/imbue-ai/gp-treemap>, and the
  package names Imbue (`hello@imbue.com`) as its author.
- gp-treemap is derived from GrandPerspective 3.6.4 by Erwin Bonsma and contributors, also GPL-2.0. Its README asks
  that the attribution to Erwin Bonsma stay visible; the page footer carries it.
- The bundle is a single-file build of readable JavaScript (not minified), so the file itself is the source form; the
  package at the URL above holds the sources it was built from.
- The page script and styles (`src/disk_map/assets/disk-map.js`, `disk-map.css`) are written against the library and run
  in the same page, so they are distributed under the same terms. The rest of the app (the Python server and scanner,
  the tests, the manifest) is covered by the same licence so the whole folder has one clear set of terms.

`src/disk_map/assets/gp-treemap.LICENSE.txt` is the same licence text, kept beside the bundle and served with it.

## What this does not cover

Code outside this folder keeps its own terms: the shared workspace libraries the app imports, and the rest of a
workspace the app is installed into.
