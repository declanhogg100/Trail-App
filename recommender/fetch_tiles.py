import os
import re
from pathlib import Path

import requests

from convert_dem_to_int16 import convert_file

DEM_TILES = [
    "N36W119", "N36W120", "N37W119", "N44E010",
    "N47W118", "N47W123", "N48W118", "N48W119", "N48W120",
    "N48W121", "N48W122", "N48W123", "N57W006",
]

LANDCOVER_TILES = [
    "N45W120", "N45W123", "N48W120", "N48W123", "N57W006",
]

TILE_RE = re.compile(r"([NS])(\d{2})([EW])(\d{3})")


def dem_url(tile: str) -> str:
    ns, lat, ew, lon = TILE_RE.match(tile).groups()
    folder = f"Copernicus_DSM_COG_10_{ns}{lat}_00_{ew}{lon}_00_DEM"
    return f"https://copernicus-dem-30m.s3.amazonaws.com/{folder}/{folder}.tif"


def landcover_url(tile: str) -> str:
    return f"https://esa-worldcover.s3.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"


def download(url: str, out_path: str) -> None:
    if os.path.exists(out_path):
        print(f"  skipping, already have {out_path}")
        return
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(resp.content)
    size_mb = os.path.getsize(out_path) / 1_000_000
    print(f"  saved {out_path} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    print("DEM tiles:")
    for tile in DEM_TILES:
        print(f"fetching {tile}...")
        out_path = f"data/dem/{tile}.tif"
        try:
            download(dem_url(tile), out_path)
            # Copernicus ships float32 -- converted to int16 immediately so
            # a fresh fetch never leaves a tile at 2x the size everything
            # else on disk already was converted down to (see
            # convert_dem_to_int16.py for why this loses no real precision)
            convert_file(Path(out_path))
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")

    print("---")
    print("Land cover tiles:")
    for tile in LANDCOVER_TILES:
        print(f"fetching {tile}...")
        try:
            download(landcover_url(tile), f"data/landcover/{tile}.tif")
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")

    print("---")
    print("done")
