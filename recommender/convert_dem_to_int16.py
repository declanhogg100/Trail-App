import sys
from pathlib import Path

import numpy as np
import rasterio

# Copernicus DEM ships as float32, but elevation in meters doesn't need
# sub-meter precision at this dataset's own 30m ground resolution -- storing
# whole meters as int16 halves disk/transfer size (4 bytes/px -> 2) with no
# meaningful accuracy loss. Earth's land elevation range (-418m to 8849m)
# fits comfortably in int16 (-32768 to 32767), so no scale factor is needed.
DEM_DIR = Path("data/dem")


def convert_file(path: Path) -> tuple[int, int]:
    with rasterio.open(path) as src:
        if src.dtypes[0] == "int16":
            return 0, 0  # already converted (e.g. a re-run after an interruption)
        data = src.read(1)
        profile = src.profile.copy()
        before = path.stat().st_size

    rounded = np.round(data).astype(np.int16)
    profile.update(dtype="int16")

    # write to a temp file and rename over the original -- atomic, so an
    # interrupted run leaves either the untouched float32 original or a
    # fully-written int16 file, never a half-written corrupt one
    tmp_path = path.with_suffix(".tmp.tif")
    with rasterio.open(tmp_path, "w", **profile) as dst:
        dst.write(rounded, 1)
    after = tmp_path.stat().st_size
    tmp_path.replace(path)

    return before, after


if __name__ == "__main__":
    paths = sorted(DEM_DIR.glob("*.tif"))
    print(f"converting {len(paths)} DEM tiles to int16...")

    total_before = total_after = 0
    for i, path in enumerate(paths):
        before, after = convert_file(path)
        total_before += before
        total_after += after
        if (i + 1) % 100 == 0 or i + 1 == len(paths):
            print(f"  {i + 1}/{len(paths)} done")

    print(f"total before: {total_before / 1e9:.2f} GB")
    print(f"total after:  {total_after / 1e9:.2f} GB")
    sys.stdout.flush()
