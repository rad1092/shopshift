"""Read public PyPI metadata for exact installed versions; keep only small evidence.

No package installation, credentials, source execution, or large downloads.
Run inside the project's environment. Wheel bytes are compressed download sizes,
not installed size, release bundle size, or summed transitive dependency size.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    records = []
    for name in ("ortools", "PySide6-Essentials", "shiboken6", "openpyxl"):
        installed = importlib.metadata.version(name)
        with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{installed}/json", timeout=20) as response:
            metadata = json.load(response)
        info = metadata["info"]
        records.append({
            "name": name, "version": installed,
            "metadata_url": f"https://pypi.org/pypi/{name}/{installed}/json",
            "requires_python": info["requires_python"],
            "license": info.get("license_expression") or info.get("license"),
            "dependencies": info.get("requires_dist"),
            "selected_wheels": [{"filename": item["filename"], "compressed_bytes": item["size"],
                                 "sha256": item["digests"]["sha256"]}
                                for item in metadata["urls"]
                                if item["packagetype"] == "bdist_wheel"
                                and any(tag in item["filename"] for tag in ("cp312", "abi3", "none-any"))],
        })
    report = {"measured_at_utc": datetime.now(timezone.utc).isoformat(),
              "host_python": platform.python_version(), "packages": records,
              "size_scope": "PyPI compressed wheels, excluding transitive dependencies and packaged application overhead"}
    encoded = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
