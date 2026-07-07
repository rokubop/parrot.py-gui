"""Load, save, snapshot, and version Talon patterns.json files.

Ground rules (see prd-talon.md):
- Round-trip fidelity: key order and unknown keys are preserved exactly
  (plain dicts keep insertion order; we only ever touch what the user edited).
- Nothing is overwritten without a snapshot: every save/deploy first copies
  the current file into ``data/talon/snapshots/``.
- Named variants live in ``data/talon/variants/<name>.json`` and can be
  deployed over the Talon-referenced path (which snapshots it first).

All functions are Qt-free and raise PatternsError with a readable message.
"""
import json
import os
import re
import shutil
import time

TALON_DATA_DIR = os.path.join("data", "talon")
SNAPSHOT_DIR = os.path.join(TALON_DATA_DIR, "snapshots")
VARIANTS_DIR = os.path.join(TALON_DATA_DIR, "variants")

_VALID_VARIANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,60}$")


class PatternsError(Exception):
    pass


# ---- basic io -----------------------------------------------------------

def load_patterns(path):
    """Parse a patterns.json into an (insertion-ordered) dict."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except OSError as exc:
        raise PatternsError(f"Couldn't read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PatternsError(f"{os.path.basename(path)} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise PatternsError(f"{os.path.basename(path)} must contain a JSON object")
    return data


def dumps_patterns(patterns):
    return json.dumps(patterns, indent=2, ensure_ascii=False) + "\n"


def save_patterns(path, patterns, snapshot_first=True, tag=""):
    """Atomically write ``patterns`` to ``path``. If the file already exists
    and snapshot_first is set, a snapshot is taken before the write.
    Returns the snapshot path (or None)."""
    snap = None
    if snapshot_first and os.path.isfile(path):
        snap = snapshot(path, tag or "pre-save")
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(dumps_patterns(patterns))
        os.replace(tmp, path)
    except OSError as exc:
        if os.path.isfile(tmp):
            os.remove(tmp)
        raise PatternsError(f"Couldn't write {path}: {exc}") from exc
    return snap


# ---- snapshots ----------------------------------------------------------

def snapshot(path, tag=""):
    """Copy ``path`` into the snapshot dir; returns the snapshot path."""
    if not os.path.isfile(path):
        raise PatternsError(f"Nothing to snapshot: {path} does not exist")
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe_tag = re.sub(r"[^A-Za-z0-9_-]+", "-", tag).strip("-")
    name = f"{stamp}__{safe_tag or 'snapshot'}.json"
    dest = os.path.join(SNAPSHOT_DIR, name)
    # Never clobber an existing snapshot from the same second
    counter = 1
    while os.path.exists(dest):
        dest = os.path.join(SNAPSHOT_DIR, f"{stamp}__{safe_tag or 'snapshot'}-{counter}.json")
        counter += 1
    try:
        shutil.copy2(path, dest)
    except OSError as exc:
        raise PatternsError(f"Couldn't snapshot to {dest}: {exc}") from exc
    return dest


def list_snapshots():
    """Newest first: [(path, mtime), ...]."""
    if not os.path.isdir(SNAPSHOT_DIR):
        return []
    entries = []
    for name in os.listdir(SNAPSHOT_DIR):
        if name.endswith(".json"):
            p = os.path.join(SNAPSHOT_DIR, name)
            entries.append((p, os.path.getmtime(p)))
    entries.sort(key=lambda e: e[1], reverse=True)
    return entries


def restore_snapshot(snapshot_path, target_path):
    """Deploy a snapshot back over the target (snapshotting the target first)."""
    patterns = load_patterns(snapshot_path)  # validate it parses
    return save_patterns(target_path, patterns, snapshot_first=True, tag="pre-restore")


# ---- variants -----------------------------------------------------------

def _variant_path(name):
    if not _VALID_VARIANT.match(name or ""):
        raise PatternsError(
            "Variant names may use letters, numbers, spaces, dots, dashes and underscores")
    return os.path.join(VARIANTS_DIR, f"{name}.json")


def list_variants():
    if not os.path.isdir(VARIANTS_DIR):
        return []
    return sorted(n[:-5] for n in os.listdir(VARIANTS_DIR) if n.endswith(".json"))


def save_variant(name, patterns):
    path = _variant_path(name)
    os.makedirs(VARIANTS_DIR, exist_ok=True)
    save_patterns(path, patterns, snapshot_first=False)
    return path


def load_variant(name):
    return load_patterns(_variant_path(name))


def delete_variant(name):
    path = _variant_path(name)
    if os.path.isfile(path):
        os.remove(path)


def deploy(patterns, target_path, tag="deploy"):
    """Write ``patterns`` over the Talon-referenced patterns.json,
    snapshotting the current file first. Returns the snapshot path."""
    return save_patterns(target_path, patterns, snapshot_first=True, tag=tag)


# ---- diff ---------------------------------------------------------------

def diff_patterns(old, new):
    """Structured diff between two patterns dicts:
    {"added": [names], "removed": [names],
     "changed": {name: [(field, old_value, new_value), ...]}}"""
    added = [n for n in new if n not in old]
    removed = [n for n in old if n not in new]
    changed = {}
    for name in new:
        if name not in old or new[name] == old[name]:
            continue
        fields = []
        keys = list(old[name].keys()) + [k for k in new[name] if k not in old[name]]
        for key in dict.fromkeys(keys):
            before, after = old[name].get(key), new[name].get(key)
            if before != after:
                fields.append((key, before, after))
        changed[name] = fields
    return {"added": added, "removed": removed, "changed": changed}
