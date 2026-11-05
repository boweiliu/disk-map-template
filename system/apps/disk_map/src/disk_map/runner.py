"""Interactive treemap of where every gigabyte on the workspace disk goes, from a saved disk scan.

Services run from /home/user/workspace (the repo root). Conventions:

- Persistent state (anything written and read across runs -- cursors,
  caches, snapshots, user records): read and write it under ``DATA_DIR``
  (defined below), never a hardcoded ``data/.apps/disk-map/`` at the
  call site. ``DATA_DIR`` defaults to ``data/.apps/disk-map/`` but
  honors the ``DISK_MAP_DATA_DIR`` env var, so an editing agent can point a
  throwaway instance at a *copy* of the data instead of the live store
  (see the update-app skill). Do NOT use ``Path(__file__)``-based
  paths for state -- the bug to avoid is one process writing to
  ``/home/user/workspace/data/.apps/...`` while another reads from
  ``/home/user/workspace/system/apps/<pkg>/data/...``.
- Static assets shipped alongside this file (templates, default
  configs, bundled JSON): ``Path(__file__).parent / "assets/..."`` is
  fine and is the right pattern.
- Listen port: bind ``PORT`` (defined below), which defaults to this
  app's assigned port but honors the ``DISK_MAP_PORT`` env var, so
  an editing agent can boot a throwaway instance on a *spare* port
  alongside the live one (see the update-app skill). Never hardcode
  the port at the ``run_simple`` call.

This is a synchronous Flask app served by the threaded Werkzeug server.
The app owns its own browser origin (the forwarder routes
``http://disk-map.<workspace-host>/`` straight to this port), so it serves
at ``/`` and root-absolute URLs, cookies, and service workers all work
unmodified -- nothing rewrites anything. Use ``flask_sock`` if you need
WebSockets.
"""

import base64
import gzip
import hashlib
import json
import multiprocessing
import os
import threading
import time
from pathlib import Path

from app_schema.api_schema import (
    DEFAULT_API_SCHEMA_PATH,
    RouteModels,
    RouteTable,
    SchemalessRoute,
    register_api_schema_route,
)
from app_schema.routes import error_response, model_response
from flask import Flask, Response, abort, request, send_file
from imbue.imbue_common.frozen_model import FrozenModel
from imbue.imbue_common.logging import setup_logging
from loguru import logger
from pydantic import Field
from werkzeug.serving import run_simple

from disk_map.scanner import scan_to_file

# Persistent state for this app lives under DATA_DIR. It defaults to
# ``data/.apps/disk-map/`` but is overridable via the ``DISK_MAP_DATA_DIR`` env var
# so a throwaway instance can run against a *copy* of the data while editing --
# see the update-app skill. Always read/write state through DATA_DIR;
# never hardcode ``data/.apps/disk-map/`` at a call site, or the override is
# bypassed. A writing call site should ``DATA_DIR.mkdir(parents=True,
# exist_ok=True)`` before writing.
DATA_DIR = Path(os.environ.get("DISK_MAP_DATA_DIR", "data/.apps/disk-map"))

# Every saved scan, one gzipped JSON file each (``scan-<unix time>.json.gz``). These are the raw
# records the page draws from; the newest is shown and older ones are kept for comparison.
SCANS_DIR = DATA_DIR / "scans"
SCANS_TO_KEEP = 20

# The browser-side files this app ships beside this module, by the name they are served under.
ASSETS_DIR = Path(__file__).parent / "assets"
ASSET_MIME_TYPES = {
    "disk-map.js": "text/javascript",
    "disk-map.css": "text/css",
    "gp-treemap.bundle.js": "text/javascript",
    "gp-treemap.LICENSE.txt": "text/plain",
}

# Listen port. Defaults to this app's assigned port but is overridable via
# the ``DISK_MAP_PORT`` env var so an editing agent can boot a throwaway
# instance on a spare port next to the live one (see the update-app skill).
# Never hardcode the port at the ``run_simple`` call, or the override is bypassed.
PORT = int(os.environ.get("DISK_MAP_PORT", "8194"))

# The browser-side modules the workspace shell builds and every app serves from
# its own origin: the app contract (how a page talks to the shell framing it) and
# the element context menu (the right-click menu whose last rows hand the
# clicked element to a chat). A module import is a fetch without cookies, which
# the forwarder refuses across origins, so they are served here rather than from
# the shell. Relative to the repo root the service runs from, like DATA_DIR.
SHELL_STATIC_MODULES_DIR = Path("system/apps/system_interface/imbue/system_interface/static/_static")
SHELL_STATIC_MODULE_NAMES = ('app_contract.js', 'context_menu.js')

# The script every page serves (keep it on every page): it connects the page to
# the shell, reports where the page is on the handshake so the shell can reopen
# this app's window at the same place, and installs the element context menu.
# A page visited outside the shell runs it harmlessly: nothing arrives, and the
# menu's Explain and Modify rows grey out.
SHELL_PAGE_SCRIPT_BODY = """
  import { connectToShell } from "/_static/app_contract.js";
  import { installElementContextMenu } from "/_static/context_menu.js";
  let handshake = null;
  const connection = connectToShell({
    onHandshake: (received) => {
      handshake = received;
      connection.location(location.pathname + location.search, document.title);
    },
  });
  installElementContextMenu({ connection, handshake: () => handshake });
"""
SHELL_PAGE_SCRIPT = f'<script type="module">{SHELL_PAGE_SCRIPT_BODY}</script>'


def inline_script_source(body: str) -> str:
    """The Content-Security-Policy source admitting one inline <script> whose body is exactly ``body``."""
    return "'sha256-" + base64.b64encode(hashlib.sha256(body.encode()).digest()).decode() + "'"


# Every HTML page is served under this policy (the app is reachable from the
# internet once the workspace is shared): scripts only from this origin plus the
# inline blocks listed here by hash, fetches, sockets and images only from this
# origin, inline styles, frames of any http(s) page, no plugins. Anything else a
# page pulls in (a CDN script, Google Fonts, an image hosted elsewhere, a
# third-party API called from the browser) is blocked until its origin is added
# to the matching directive; a new inline <script> needs its
# ``inline_script_source`` added.
# The browser posts every block to ``/_csp-report`` below, which logs it on
# stderr (the supervisor log), so a blocked resource is never silent; the
# ``'report-sample'`` makes the browser include where a blocked inline script
# is and how it starts, since the report otherwise names it only as "inline".
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    f"script-src 'self' 'report-sample' {inline_script_source(SHELL_PAGE_SCRIPT_BODY)}; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; frame-src http: https:; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; "
    "report-uri /_csp-report"
)
BROWSER_EXTENSION_SCHEMES = ("chrome-extension:", "moz-extension:", "safari-web-extension:")


class HealthResponse(FrozenModel):
    """What the health probe answers."""

    status: str = Field(description="Always 'ok'")


class RescanStatus(FrozenModel):
    """Whether a disk scan is running, and how the last one went."""

    is_running: bool = Field(description="True while a scan is in progress")
    started_at: float | None = Field(description="Unix time the current or last scan started; None before the first")
    finished_at: float | None = Field(description="Unix time the last scan finished; None while one runs or before the first")
    error: str | None = Field(description="Why the last scan failed; None when it succeeded or none has run")
    latest_scan_at: int | None = Field(description="Unix time of the newest saved scan; None when there is none")


def saved_scan_paths() -> list[Path]:
    """Every saved scan, oldest first (the unix time in the name sorts as text)."""
    return sorted(SCANS_DIR.glob("scan-*.json.gz"))


def latest_scan_time() -> int | None:
    paths = saved_scan_paths()
    return int(paths[-1].name.removeprefix("scan-").removesuffix(".json.gz")) if paths else None


class RescanTracker:
    """Runs at most one disk scan at a time, in a child process so a huge walk never bloats this server."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._is_running = False
        self._started_at: float | None = None
        self._finished_at: float | None = None
        self._error: str | None = None

    def status(self) -> RescanStatus:
        with self._lock:
            return RescanStatus(
                is_running=self._is_running,
                started_at=self._started_at,
                finished_at=self._finished_at,
                error=self._error,
                latest_scan_at=latest_scan_time(),
            )

    def start(self) -> None:
        """Begin a scan unless one is already running."""
        with self._lock:
            if self._is_running:
                return
            self._is_running = True
            self._started_at = time.time()
            self._finished_at = None
            self._error = None
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        SCANS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = SCANS_DIR / f"scan-{int(time.time())}.json.gz"
        # A process of its own, so walking hundreds of thousands of files never bloats this server.
        scan_process = multiprocessing.get_context("spawn").Process(target=scan_to_file, args=(out_path,))
        scan_process.start()
        scan_process.join()
        error: str | None = None
        if scan_process.exitcode != 0:
            error = f"the scan stopped unexpectedly (exit code {scan_process.exitcode}); see the app's error log"
        if error is None:
            for old_path in saved_scan_paths()[:-SCANS_TO_KEEP]:
                old_path.unlink(missing_ok=True)
        else:
            logger.error("Disk scan failed: {}", error)
        with self._lock:
            self._is_running = False
            self._finished_at = time.time()
            self._error = error


rescan_tracker = RescanTracker()


# What every route exchanges, which the app's API document publishes and every parse and answer
# is checked against (build-app skill, "The app describes its own API"): a route that reads or
# answers JSON names its pydantic models here and uses ``parse_request_body`` and
# ``model_response``; a page, a file or a stream is declared schemaless with the reason.
ROUTE_TABLE: RouteTable = {
    ("GET", "/"): SchemalessRoute(reason="the app's page"),
    ("GET", "/assets/{basename}"): SchemalessRoute(reason="a script, stylesheet or licence the page loads"),
    ("GET", "/api/scan"): SchemalessRoute(reason="the newest saved disk scan: a large JSON tree of folders and sizes"),
    ("GET", "/api/scan/raw"): SchemalessRoute(reason="the same scan, pretty-printed for reading"),
    ("GET", "/api/rescan"): RouteModels(response_model=RescanStatus),
    ("POST", "/api/rescan"): RouteModels(response_model=RescanStatus, success_status=202),
    ("GET", "/_static/{basename}"): SchemalessRoute(reason="a browser-side module the shell builds"),
    ("GET", "/health"): RouteModels(response_model=HealthResponse),
    ("POST", "/_csp-report"): SchemalessRoute(reason="the browser's report of what the page's policy blocked"),
}

app = Flask("disk_map", static_folder=None)
# The app describes its own API: an OpenAPI document of every route below, served at the
# manifest's api_schema_path.
register_api_schema_route(
    app, DEFAULT_API_SCHEMA_PATH, title='Disk Map', description='Interactive treemap of where every gigabyte on the workspace disk goes, from a saved disk scan.', route_table=ROUTE_TABLE
)


@app.after_request
def add_content_security_policy(response: Response) -> Response:
    if response.mimetype == "text/html":
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    return response


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Disk Map</title>
<link rel="stylesheet" href="/assets/disk-map.css">
</head>
<body>
<header>
  <h1>Disk Map</h1>
  <div id="summary">Loading the latest scan...</div>
  <div class="actions">
    <span id="rescan-note"></span>
    <button id="rescan" type="button">Scan again</button>
  </div>
</header>
<main>
  <aside id="biggest" aria-label="Biggest folders and files"></aside>
  <section id="map-pane"><gp-treemap id="map" color-mode="level1" gradient-intensity="0.6" min-cell-area="30" display-depth="4"></gp-treemap></section>
</main>
<footer>
  <div id="detail">Click a block to see what it is.</div>
  <div class="links">
    <button id="copy-path" type="button" hidden>Copy path</button>
    <a id="raw-link" href="/api/scan/raw" target="_blank" rel="noopener">raw scan</a>
    <a href="/assets/gp-treemap.LICENSE.txt" target="_blank" rel="noopener">treemap by gp-treemap (GPL-2.0), after GrandPerspective by Erwin Bonsma</a>
  </div>
</footer>
<script src="/assets/gp-treemap.bundle.js"></script>
<script src="/assets/disk-map.js"></script>
""" + SHELL_PAGE_SCRIPT + """
</body>
</html>
"""


@app.route("/")
def index() -> Response:
    """The app's page."""
    return Response(INDEX_HTML, mimetype="text/html")


@app.route("/assets/<basename>")
def asset(basename: str) -> Response:
    """A script, stylesheet or licence the page loads."""
    mime_type = ASSET_MIME_TYPES.get(basename)
    if mime_type is None:
        abort(404)
    return send_file(ASSETS_DIR / basename, mimetype=mime_type, max_age=0)


def read_latest_scan_text(indent: int | None) -> str | None:
    """The newest saved scan as JSON text (compact, or indented for reading); None when none is saved."""
    paths = saved_scan_paths()
    if not paths:
        return None
    with gzip.open(paths[-1], "rt", encoding="utf-8") as handle:
        scan = json.load(handle)
    return json.dumps(scan, indent=indent, separators=(",", ":") if indent is None else None)


@app.route("/api/scan")
def latest_scan() -> Response:
    """The newest saved disk scan as JSON: a tree of folders and sizes, with when it was taken."""
    text = read_latest_scan_text(None)
    if text is None:
        return error_response("No scan has been saved yet.", 404)
    return Response(text, mimetype="application/json")


@app.route("/api/scan/raw")
def latest_scan_raw() -> Response:
    """The newest saved disk scan, pretty-printed so a person can read it."""
    text = read_latest_scan_text(1)
    if text is None:
        return error_response("No scan has been saved yet.", 404)
    return Response(text, mimetype="application/json")


@app.route("/api/rescan")
def rescan_status() -> Response:
    """Whether a scan is running and how the last one went."""
    return model_response(rescan_tracker.status())


@app.route("/api/rescan", methods=["POST"])
def rescan_start() -> Response:
    """Start a fresh disk scan unless one is already running; takes about a minute and a half."""
    rescan_tracker.start()
    return model_response(rescan_tracker.status(), 202)


@app.route("/_csp-report", methods=["POST"])
def content_security_policy_report() -> Response:
    """Where the browser reports what the page's security policy blocked."""
    body = request.get_json(force=True, silent=True)
    report = body.get("csp-report") if isinstance(body, dict) else None
    if not isinstance(report, dict):
        return Response(status=204)
    blocked, page, source, directive, line, sample = (
        str(report.get(key, ""))[:500]
        for key in ("blocked-uri", "document-uri", "source-file", "effective-directive", "line-number", "script-sample")
    )
    # A block caused by a browser extension is the policy doing its job and is not logged.
    if blocked.startswith(BROWSER_EXTENSION_SCHEMES) or source.startswith(BROWSER_EXTENSION_SCHEMES):
        return Response(status=204)
    # An inline script or style is reported as "inline": say where it is and how it starts instead.
    where = f" at {source}:{line}" if source and line else ""
    starting = f" starting {sample!r}" if sample else ""
    remedy = (
        "add its inline_script_source to CONTENT_SECURITY_POLICY if the page needs it"
        if blocked == "inline"
        else "add its origin to CONTENT_SECURITY_POLICY if the page needs it"
    )
    logger.error(
        "Content-Security-Policy blocked {!r} on {!r} ({}){}{}; {}", blocked, page, directive, where, starting, remedy
    )
    return Response(status=204)


@app.route("/_static/<basename>")
def shell_module(basename: str) -> Response:
    """One of the two browser-side modules the workspace shell builds and every app serves from its own origin."""
    # The two shell-built modules and nothing else: a name that is not one of
    # them is a 404, so this route can never read outside that directory.
    if basename not in SHELL_STATIC_MODULE_NAMES:
        abort(404)
    module_path = SHELL_STATIC_MODULES_DIR / basename
    if not module_path.is_file():
        abort(404)
    # Flask resolves a relative path against the app's own directory, not the cwd.
    return send_file(module_path.absolute(), mimetype="text/javascript")


@app.route("/health")
def health() -> Response:
    """Whether the app is up."""
    return model_response(HealthResponse(status="ok"))


def main() -> None:
    setup_logging()
    run_simple(
        "127.0.0.1", PORT, app, threaded=True, use_reloader=False, use_debugger=False
    )


if __name__ == "__main__":
    main()
