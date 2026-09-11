"""Write or verify SHA-256 sidecars for release files."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write(path: Path) -> Path:
    sidecar = path.with_name(path.name + ".sha256")
    sidecar.write_text(f"{digest(path)}  {path.name}\n", encoding="ascii")
    return sidecar


def verify(sidecar: Path) -> None:
    expected, separator, filename = sidecar.read_text(encoding="ascii").strip().partition("  ")
    if not separator or not expected or not filename:
        raise ValueError(f"Invalid checksum sidecar: {sidecar}")
    artifact = sidecar.parent / filename
    actual = digest(artifact)
    if actual != expected.lower():
        raise ValueError(f"Checksum mismatch for {artifact}: expected {expected}, got {actual}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("write", "verify"))
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.paths:
        if args.mode == "write":
            print(write(path))
        else:
            verify(path)
            print(path)


if __name__ == "__main__":
    main()
