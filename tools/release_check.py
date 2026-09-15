"""Audit built-wheel membership and byte identity; not a secret scanner or native acceptance."""

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METADATA = {"METADATA", "WHEEL", "RECORD", "entry_points.txt", "top_level.txt"}
SUFFIXES = {".py", ".js", ".css", ".html", ".json"}


def audit(path):
    source = ROOT / "src"
    expected = {
        p.relative_to(source).as_posix(): p.read_bytes()
        for p in (source / "image_queue").rglob("*")
        if p.is_file() and p.suffix in SUFFIXES
    }
    with zipfile.ZipFile(path) as wheel:
        names = wheel.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate wheel members")
        for name in names:
            if name in expected:
                if wheel.read(name) != expected.pop(name):
                    raise ValueError("Wheel differs from reviewed source")
            elif not (
                name.startswith("arena_image_queue-")
                and name.count("/") == 1
                and name.split("/")[0].endswith(".dist-info")
                and name.split("/")[1] in METADATA
            ):
                raise ValueError("Unexpected wheel member; release refused")
        if expected:
            raise ValueError("Runtime source/assets missing from wheel")
    return len(names)


if __name__ == "__main__":
    print(f"PASS: {audit(Path(sys.argv[1]))} wheel members match source/metadata allowlist")
