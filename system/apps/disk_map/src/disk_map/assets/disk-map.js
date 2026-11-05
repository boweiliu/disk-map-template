// Disk Map page: draws the newest saved scan with <gp-treemap> and lists the biggest things.
(function () {
  "use strict";

  const treemap = document.getElementById("map");
  const summaryEl = document.getElementById("summary");
  const biggestEl = document.getElementById("biggest");
  const detailEl = document.getElementById("detail");
  const rescanButton = document.getElementById("rescan");
  const rescanNote = document.getElementById("rescan-note");
  const copyButton = document.getElementById("copy-path");

  const BIGGEST_FOLDER_COUNT = 18;
  const BIGGEST_FOLDER_SHOWN = 24;
  const BIGGEST_FILE_COUNT = 8;
  const MIN_LISTED_FRACTION = 0.003;

  // Every node by the id the treemap knows it by.
  let nodesById = new Map();
  let scan = null;
  let selectedPath = "";

  function fmtBytes(value) {
    const units = ["B", "KB", "MB", "GB", "TB"];
    let n = value || 0;
    let i = 0;
    while (n >= 1000 && i < units.length - 1) {
      n /= 1000;
      i++;
    }
    return (n >= 100 || i === 0 ? n.toFixed(0) : n >= 10 ? n.toFixed(1) : n.toFixed(2)) + " " + units[i];
  }

  function fmtDate(seconds) {
    if (!seconds) return "";
    const d = new Date(seconds * 1000);
    const pad = (n) => String(n).padStart(2, "0");
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }

  function fmtAgo(seconds) {
    const diff = Math.max(0, Date.now() / 1000 - seconds);
    if (diff < 90) return "just now";
    if (diff < 5400) return Math.round(diff / 60) + " min ago";
    if (diff < 129600) return Math.round(diff / 3600) + " h ago";
    return Math.round(diff / 86400) + " days ago";
  }

  function joinPath(parentPath, name) {
    if (parentPath === "") return name;
    return parentPath === "/" ? "/" + name : parentPath + "/" + name;
  }

  // Give every node an id, its full path, and a label; remember it for lookups.
  function prepare(node, parentPath, counter) {
    node._id = counter.next++;
    node._path = node._isRoot ? "" : joinPath(parentPath, node.name);
    node._label = node._isRoot ? "Whole disk" : node.name === "/" ? "system disk (/)" : node.name;
    nodesById.set(node._id, node);
    if (node.children) {
      for (const child of node.children) {
        child._parent = node;
        prepare(child, node._path, counter);
      }
    }
  }

  // The list of biggest things, built by repeatedly opening the largest folder into its parts until
  // the list is long enough. Every byte sits in exactly one entry, and the entries add up to the whole.
  function biggestSlices(root) {
    const minSize = root.size * MIN_LISTED_FRACTION;
    let items = root.children.slice();
    while (items.length < BIGGEST_FOLDER_COUNT) {
      let best = -1;
      for (let i = 0; i < items.length; i++) {
        if (items[i].children && (best < 0 || items[i].size > items[best].size)) best = i;
      }
      if (best < 0) break;
      const node = items[best];
      const parts = node.children.filter((c) => c.size >= minSize);
      const rest = node.size - parts.reduce((sum, c) => sum + c.size, 0);
      if (rest >= minSize) {
        // Everything too small to list on its own stays attached to the folder it came from.
        parts.push({ _id: node._id, _path: joinPath(node._path, "(smaller items)"), _parent: node, size: rest, synthetic: true });
      }
      items.splice(best, 1, ...parts);
    }
    return items;
  }

  // The biggest entries only, so the list stays short; the rest is summed into one line.
  function trimmedSlices(root) {
    const minSize = root.size * MIN_LISTED_FRACTION;
    const items = biggestSlices(root).sort((a, b) => b.size - a.size);
    const shown = items.slice(0, BIGGEST_FOLDER_SHOWN).filter((c) => c.size >= minSize);
    const hidden = items.filter((c) => !shown.includes(c));
    return { shown, hiddenBytes: hidden.reduce((sum, c) => sum + c.size, 0), hiddenCount: hidden.length };
  }

  function biggestFiles(root) {
    const files = [];
    (function visit(node) {
      if (node.file) files.push(node);
      if (node.children) node.children.forEach(visit);
    })(root);
    files.sort((a, b) => b.size - a.size);
    return files.slice(0, BIGGEST_FILE_COUNT);
  }

  function listItem(node, total) {
    const li = document.createElement("li");
    li.dataset.nodeId = String(node._id);
    li.title = node._path;
    const bar = document.createElement("div");
    bar.className = "bar";
    bar.style.width = Math.max(1, (node.size / total) * 100) + "%";
    const row = document.createElement("div");
    row.className = "row";
    const path = document.createElement("span");
    path.className = "path";
    path.textContent = node._path;
    const size = document.createElement("span");
    size.className = "size";
    size.textContent = fmtBytes(node.size);
    row.append(path, size);
    li.append(bar, row);
    return li;
  }

  function addHeading(text) {
    const h = document.createElement("h2");
    h.textContent = text;
    biggestEl.append(h);
  }

  function addNote(text, className) {
    const p = document.createElement("p");
    p.className = "note" + (className ? " " + className : "");
    p.textContent = text;
    biggestEl.append(p);
  }

  function renderSidebar(root, data) {
    biggestEl.replaceChildren();
    addHeading("Where the space is");
    const ol = document.createElement("ol");
    const { shown, hiddenBytes, hiddenCount } = trimmedSlices(root);
    for (const node of shown) ol.append(listItem(node, root.size));
    biggestEl.append(ol);
    if (hiddenBytes >= root.size * MIN_LISTED_FRACTION) {
      addNote("Everything else: " + fmtBytes(hiddenBytes) + " in " + hiddenCount + " smaller entries.");
    }

    addHeading("Biggest single files");
    const fileList = document.createElement("ol");
    for (const node of biggestFiles(root)) fileList.append(listItem(node, root.size));
    biggestEl.append(fileList);

    const hidden = data.df_used_bytes - root.size;
    if (hidden > 0.02 * data.df_used_bytes) {
      addNote(
        fmtBytes(hidden) +
          " of the disk's reported use is not visible from inside this workspace (for example files that " +
          "were deleted but are still open).",
        "warn"
      );
    }
    if (data.hardlink_bytes_counted_once > 0) {
      addNote(
        fmtBytes(data.hardlink_bytes_counted_once) +
          " is shared between several names (hard links) and counted once, under whichever path was reached first."
      );
    }
  }

  function renderSummary(data, root) {
    summaryEl.replaceChildren();
    const b = (text) => {
      const el = document.createElement("b");
      el.textContent = text;
      return el;
    };
    summaryEl.append(
      b(fmtBytes(root.size)),
      " found in files. The disk holds ",
      b(fmtBytes(data.df_total_bytes)),
      " and has ",
      b(fmtBytes(data.df_free_bytes)),
      " free. Scanned " + fmtAgo(data.scanned_at) + "."
    );
  }

  function renderDetail() {
    const id = treemap._focusId != null ? treemap._focusId : treemap._targetId;
    const node = id == null ? null : nodesById.get(Number(id));
    if (!node || !scan) {
      selectedPath = "";
      detailEl.textContent = "Click a block to see what it is.";
      copyButton.hidden = true;
      return;
    }
    selectedPath = node._path;
    const parts = [];
    const share = (node.size / scan.tree.size) * 100;
    parts.push(fmtBytes(node.size) + " (" + (share >= 10 ? share.toFixed(0) : share.toFixed(1)) + "% of what was found)");
    if (node.files) parts.push(node.files.toLocaleString() + " files");
    if (node.dirs) parts.push(node.dirs.toLocaleString() + " folders");
    if (node.mtime) parts.push("last changed " + fmtDate(node.mtime));
    detailEl.replaceChildren();
    const path = document.createElement("b");
    path.textContent = node._path || "Whole disk";
    const rest = document.createElement("span");
    rest.className = "muted";
    rest.textContent = "  |  " + parts.join("  |  ");
    detailEl.append(path, rest);
    copyButton.hidden = !node._path;
  }

  function draw(data) {
    scan = data;
    nodesById = new Map();
    const root = data.tree;
    root._isRoot = true;
    prepare(root, "", { next: 1 }); // ids start at 1: the treemap treats a falsy id as "none"
    treemap.getId = (n) => n._id;
    treemap.getChildren = (n) => n.children || [];
    treemap.getValue = (n) => n.size; // a folder's weight is its whole size; the treemap opens folders lazily
    treemap.getLabel = (n) => n._label;
    treemap.getColor = (n) => n._id;
    treemap.valueFormatter = fmtBytes;
    treemap.root = root;
    renderSummary(data, root);
    renderSidebar(root, data);
    renderDetail();
  }

  async function loadScan() {
    const response = await fetch("/api/scan");
    if (response.status === 404) {
      summaryEl.textContent = "No scan has been taken yet. Scanning now (about a minute and a half)...";
      await startRescan();
      return;
    }
    draw(await response.json());
  }

  async function pollRescan() {
    const status = await (await fetch("/api/rescan")).json();
    if (status.is_running) {
      const seconds = Math.round(Date.now() / 1000 - status.started_at);
      rescanNote.className = "";
      rescanNote.textContent = "Scanning... " + seconds + " s";
      rescanButton.disabled = true;
      setTimeout(pollRescan, 2000);
      return;
    }
    rescanButton.disabled = false;
    if (status.error) {
      rescanNote.className = "error";
      rescanNote.textContent = "The scan failed: " + status.error;
      return;
    }
    rescanNote.className = "";
    rescanNote.textContent = "";
    await loadScan();
  }

  async function startRescan() {
    rescanButton.disabled = true;
    await fetch("/api/rescan", { method: "POST" });
    await pollRescan();
  }

  biggestEl.addEventListener("click", (event) => {
    const li = event.target.closest("li[data-node-id]");
    if (!li) return;
    const node = nodesById.get(Number(li.dataset.nodeId));
    if (!node) return;
    // Zoom into the folder; a file is shown inside its folder with the file itself selected.
    const zoomId = node.file || node.pooled ? node._parent._id : node._id;
    treemap.zoomTo(zoomId);
    treemap._setFocus(node._id);
    renderDetail();
  });

  copyButton.addEventListener("click", async () => {
    if (!selectedPath) return;
    await navigator.clipboard.writeText(selectedPath);
    copyButton.textContent = "Copied";
    setTimeout(() => (copyButton.textContent = "Copy path"), 1200);
  });

  rescanButton.addEventListener("click", startRescan);
  for (const name of ["gp-focus", "gp-target", "gp-zoom-change"]) treemap.addEventListener(name, renderDetail);

  // Show whatever scan exists; if a scan is already running (started elsewhere), follow it.
  fetch("/api/rescan")
    .then((r) => r.json())
    .then((status) => (status.is_running ? pollRescan() : loadScan()));
})();
