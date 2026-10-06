#!/usr/bin/env python3
"""Build a clean local marketplace, excluding VCS, migration metadata and caches."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = (".agents", ".claude-plugin", ".codex-plugin", "hooks", "integrations",
           "codex-skills", "commands", "workflows", "scripts", "docs",
           "README.md", "LICENSE", "CHANGELOG.md")


def build(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("Destination already exists; choose an empty new directory.")
    if destination == ROOT or ROOT in destination.parents and destination.parts[len(ROOT.parts)] != "dist":
        raise ValueError("Within the repository, packages must be built under dist/.")
    files = []
    for entry in INCLUDE:
        source = ROOT / entry
        if not source.exists():
            continue
        for item in sorted(source.rglob("*") if source.is_dir() else [source]):
            relative = item.relative_to(ROOT)
            if any(part in (".git", ".migrar-projeto", "__pycache__", ".DS_Store") for part in relative.parts):
                continue
            if item.is_symlink():
                raise ValueError("Package source contains a symlink: %s" % relative)
            if item.is_file() and item.suffix != ".pyc":
                files.append((item, relative))
    destination.mkdir(parents=True)
    hashes = {}
    for source, relative in files:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        hashes[str(relative)] = hashlib.sha256(target.read_bytes()).hexdigest()
    (destination / "PACKAGE-MANIFEST.json").write_text(json.dumps(hashes, indent=2) + "\n")
    return hashes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination")
    args = parser.parse_args()
    print("Packaged %d files." % len(build(args.destination)))
