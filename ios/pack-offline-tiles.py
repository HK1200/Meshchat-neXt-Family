#!/usr/bin/env python3
"""Pack the existing PNG map assets into two iOS bundle resources."""

import json
from pathlib import Path
import sys


def pack(assets: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    index = {}
    with (output / "tiles.bin").open("wb") as stream:
        for region in ("pnw", "whatcom"):
            region_root = assets / f"{region}-tiles"
            paths = sorted(region_root.glob("*/*/*.png"))
            if not paths:
                raise ValueError(f"No bundled tiles found in {region_root}")
            for path in paths:
                key = path.relative_to(region_root).with_suffix("").as_posix()
                if key in index:
                    raise ValueError(f"Overlapping bundled tile coordinates: {key}")
                data = path.read_bytes()
                if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ValueError(f"Invalid bundled PNG: {path}")
                index[key] = [stream.tell(), len(data)]
                stream.write(data)
    (output / "index.json").write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    pack(Path(sys.argv[1]), Path(sys.argv[2]))
