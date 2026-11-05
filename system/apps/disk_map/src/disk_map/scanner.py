"""Scan disk usage into a compact folder tree and save it as gzipped JSON.

Sizes are real on-disk bytes (blocks used, not file length), each hard-linked file is
counted once (the first path walked owns it), symlinks are never followed, and a scan
never crosses into another mount. Folders smaller than ``COLLAPSE_BELOW_BYTES`` become a
single leaf and files smaller than ``FILE_LEAF_MIN_BYTES`` are pooled per folder, so the
saved tree stays small enough to draw in a browser; those bytes still count in every
parent, so every total adds up to the real figure.
"""

import argparse
import gzip
import json
import os
import stat
import time
from pathlib import Path
from typing import Any

from loguru import logger

COLLAPSE_BELOW_BYTES = 2 * 1024 * 1024
FILE_LEAF_MIN_BYTES = 1024 * 1024

# Filesystems that hold real data; everything else (proc, tmpfs, cgroups, ...) is not disk.
DISK_FILESYSTEMS = frozenset({"9p", "ext4", "xfs", "btrfs", "overlay", "virtiofs", "zfs", "fuseblk", "nfs", "nfs4"})

type Node = dict[str, Any]


def detect_scan_roots(mounts_text: str) -> list[str]:
    """The mount points of disk-backed filesystems that are folders, outermost first."""
    roots: list[str] = []
    for line in mounts_text.splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        mount_point, fs_type = fields[1].replace("\\040", " "), fields[2]
        if fs_type in DISK_FILESYSTEMS and os.path.isdir(mount_point) and mount_point not in roots:
            roots.append(mount_point)
    return sorted(roots, key=lambda path: (path.count("/"), path))


class TreeScanner:
    """Walks one or more mounts and builds the size tree."""

    def __init__(self) -> None:
        self.seen_inodes: set[tuple[int, int]] = set()
        self.errors: list[str] = []
        self.hardlink_bytes_skipped = 0

    def _disk_bytes(self, info: os.stat_result) -> int:
        used = info.st_blocks * 512
        return used if used > 0 else info.st_size

    def scan_dir(self, path: str, name: str, root_device: int) -> Node:
        try:
            with os.scandir(path) as listing:
                entries = list(listing)
        except OSError as error:
            self.errors.append(f"{path}: {error}")
            return {"name": name, "size": 0, "files": 0, "dirs": 0, "mtime": 0}
        own_bytes = 0
        newest = 0
        try:
            own = os.lstat(path)
            own_bytes = self._disk_bytes(own)
            newest = int(own.st_mtime)
        except OSError as error:
            self.errors.append(f"{path}: {error}")
        size = own_bytes
        files = 0
        dirs = 0
        children: list[Node] = []
        pooled_bytes = own_bytes
        pooled_count = 0
        for entry in entries:
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as error:
                self.errors.append(f"{entry.path}: {error}")
                continue
            if stat.S_ISDIR(info.st_mode):
                if info.st_dev != root_device:
                    continue
                child = self.scan_dir(entry.path, entry.name, root_device)
                dirs += 1 + child["dirs"]
                files += child["files"]
                size += child["size"]
                newest = max(newest, child["mtime"])
                children.append(child)
                continue
            files += 1
            newest = max(newest, int(info.st_mtime))
            file_bytes = self._disk_bytes(info)
            if info.st_nlink > 1 and stat.S_ISREG(info.st_mode):
                inode_key = (info.st_dev, info.st_ino)
                if inode_key in self.seen_inodes:
                    self.hardlink_bytes_skipped += file_bytes
                    continue
                self.seen_inodes.add(inode_key)
            size += file_bytes
            if file_bytes >= FILE_LEAF_MIN_BYTES:
                children.append({"name": entry.name, "size": file_bytes, "mtime": int(info.st_mtime), "file": True})
            else:
                pooled_bytes += file_bytes
                pooled_count += 1
        node: Node = {"name": name, "size": size, "files": files, "dirs": dirs, "mtime": newest}
        if size < COLLAPSE_BELOW_BYTES:
            node["collapsed"] = True
            return node
        if pooled_bytes > 0:
            pool_name = f"({pooled_count} small files)" if pooled_count else "(folder entries)"
            children.append(
                {"name": pool_name, "size": pooled_bytes, "files": pooled_count, "mtime": newest, "pooled": True}
            )
        children.sort(key=lambda child: child["size"], reverse=True)
        node["children"] = children
        return node


def scan_disk(roots: list[str]) -> Node:
    """The saved-scan record for ``roots``: the tree plus how it was made and how the disk reports itself."""
    started = time.time()
    scanner = TreeScanner()
    root_nodes: list[Node] = []
    for root in roots:
        began = time.time()
        node = scanner.scan_dir(root, root, os.lstat(root).st_dev)
        logger.info("scanned {}: {:.2f} GB in {:.0f}s", root, node["size"] / 1e9, time.time() - began)
        root_nodes.append(node)
    fs = os.statvfs(roots[0])
    return {
        "scanned_at": int(started),
        "duration_seconds": round(time.time() - started, 1),
        "roots": roots,
        "df_total_bytes": fs.f_blocks * fs.f_frsize,
        "df_used_bytes": (fs.f_blocks - fs.f_bfree) * fs.f_frsize,
        "df_free_bytes": fs.f_bavail * fs.f_frsize,
        "collapse_below_bytes": COLLAPSE_BELOW_BYTES,
        "file_leaf_min_bytes": FILE_LEAF_MIN_BYTES,
        "hardlink_bytes_counted_once": scanner.hardlink_bytes_skipped,
        "error_count": len(scanner.errors),
        "errors_sample": scanner.errors[:50],
        "tree": {"name": "disk", "size": sum(node["size"] for node in root_nodes), "children": root_nodes},
    }


def write_scan(scan: Node, out_path: Path) -> None:
    """Save ``scan`` as gzipped JSON, atomically so a reader never sees half a file."""
    partial = out_path.with_name(out_path.name + ".part")
    with gzip.open(partial, "wt", encoding="utf-8") as handle:
        json.dump(scan, handle, separators=(",", ":"))
    partial.replace(out_path)


def scan_to_file(out_path: Path, roots: list[str] | None = None) -> None:
    """Scan ``roots`` (default: every disk-backed mount) and save the result at ``out_path``."""
    scan_roots = roots or detect_scan_roots(Path("/proc/mounts").read_text())
    write_scan(scan_disk(scan_roots), out_path)
    logger.info("wrote {}", out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan disk usage into a saved tree.")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("roots", nargs="*", help="mount points to scan; default: every disk-backed mount")
    args = parser.parse_args()
    scan_to_file(args.out, args.roots)


if __name__ == "__main__":
    main()
