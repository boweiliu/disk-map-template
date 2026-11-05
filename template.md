---
title: "Disk Map"
description: "An interactive treemap of where every gigabyte on the workspace disk goes, drawn from a saved disk scan."
thumbnail: "template.svg"
version: v1
format: v2
---

# Disk Map

This file is the manifest for the **Disk Map** template (slug:
`disk-map`). It is the one document a future agent reads to understand,
present, and adapt this template. If you are an agent in a workspace that was
created from this template, this file is your script: read all of it, then
follow "How to adapt it" below.

## What it is

Disk Map answers the question "where did my disk space go?" It scans every disk-backed mount of the workspace, saves the result, and draws it as an explorable treemap: every folder and large file is a block whose area is its real size on disk, so the biggest consumers stand out at a glance. Clicking a block shows what it is and lets you copy its path; a list of the biggest items sits beside the map. A scan takes about a minute and a half, runs in a process of its own, and can be started from the page at any time; the newest 20 scans are kept so they can be compared. The page opens as a window in the workspace.

## How it works

The snapshot includes these paths (each is a repo-root-relative path copied
from the original agent onto a clean default-workspace-template base):

- `system/apps/disk_map`
- `system/supervisord.conf.d/disk-map.conf`

The snapshot includes these paths:

- `system/apps/disk_map` -- the app. `scanner.py` walks the disk (real on-disk bytes, each hard-linked file counted once, symlinks never followed, never crossing into another mount, small folders and files pooled so every parent total still adds up) and saves a compact tree as `scan-<unix time>.json.gz`. `runner.py` is a Flask server that serves the page and its assets, the newest scan at `/api/scan` (and pretty-printed at `/api/scan/raw`), starts a new scan with `POST /api/rescan` in a separate process, and describes its own API at `/api/schema`. `assets/` holds the page script and styles and the bundled gp-treemap library (GPL-2.0, with its license text beside it). It is its own uv project (`pyproject.toml`, `uv.lock`) that takes the shared `app-schema` library from the workspace, has a test of its API document (`runner_test.py`) and the workspace's standard code-quality ratchets, and an `app.toml` that makes it appear as the "Disk Map" window.
- `system/supervisord.conf.d/disk-map.conf` -- the supervisord program that syncs the app's environment, registers its port with `forward_port.py` (`http://localhost:8194`, changeable with `DISK_MAP_PORT`), and runs it.

Saved scans live under `data/.apps/disk-map/scans/` (or `DISK_MAP_DATA_DIR`). They are the raw records the page is drawn from, and they list the files of the machine they were taken on, which is why none ship with the template. With no scan saved, the page starts one on first load.

## Recipe

This template is version `v1`. It is not a fork of the
workspace it came from -- it is DERIVED from it by a recipe: include these
paths, leave these out, apply these published-version rules. An update re-runs
the recipe against the current workspace and publishes the result as the next
version, so anything excluded stays excluded even though it still exists in the
source workspace.

The recipe is machine-read, so it lives in the sibling
[`template.toml`](template.toml) -- its `[recipe]` table -- along with
the structured requirements and the environment this template needs
installed. That file is authoritative for all of it; this one holds the prose.

## Requirements

Everything the adopting agent must deal with before this template is really
theirs. Two kinds of entry, handled at different times:

- **Activation** -- what must be SET UP before anything runs, in the
  machine-readable `requires_` forms below. The adopting agent acts on these
  ITSELF, first, before asking anything.
- **Adaptation** -- what must be DECIDED or REWIRED, in prose. Worked through
  interactively with the user, after activation.


No requirements -- runs as published, with no external permissions or secrets.

## Environment

What this template needs INSTALLED, beyond what the template already has.
Declared in `template.toml`'s `[environment]` table; an adopting agent
converges it at ITS OWN pinned apt snapshot timestamp, so package versions come
out consistent with the rest of that agent's environment rather than frozen to
whatever this publisher happened to have.

Nothing extra -- runs on the stock workspace environment.

## How to adapt it

Instructions for the NEXT agent -- the one adapting this template into a
new agent. This is the `use-template` skill's template path; in short:

1. Read this entire file first, especially "Requirements" below. It holds two
   kinds of entry and they are handled at different times: the machine-readable
   `requires_` lines are ACTIVATION (set them up before anything runs), and
   the prose bullets are ADAPTATION (decide or rewire them afterwards).
2. Present the template to the user in plain, non-technical language: what
   it is, what it does, and what it needs from them (name the activation
   requirements).
3. Ask whether they want to use the same connectors (e.g. their own Slack).
   If YES: ACTIVATE FIRST -- initiate every `requires_permission` line NOW
   via a latchkey permission request (see the `connect-external-service` skill; the request
   opens the approval/login flow in the Imbue Studio app), wire up any
   `requires_secret` values, start the services, and get the app showing
   THE USER'S OWN DATA. Done for a data-backed app means the user can open it
   and see their own data -- NOT that a service starts or an endpoint returns
   200. Then tell them it is live and to take a look.
4. Only AFTER that (or immediately, if they chose different connectors -- the
   swap is then the first adaptation) ask: "How do you want to adapt it?"
5. Work through each requirement interactively, one at a time. Translate each
   into plain language, ask for a decision only when you genuinely need one,
   and resolve the obvious ones yourself.
6. When done, append a dated entry to "Adaptation history" below (never
   rewrite earlier entries) and commit.

## Publication history

This template's changelog: what each published version changed. The PUBLISHER
appends one entry per version (newest last); earlier entries are never rewritten.
This is distinct from "Adaptation history" below, which is the ADOPTERS' log.

### v1 (2026-11-05) -- first publication: the Disk Map app and its program entry

## Adaptation history

Each agent that adapts this template appends one dated entry below. Earlier
entries are never rewritten.
