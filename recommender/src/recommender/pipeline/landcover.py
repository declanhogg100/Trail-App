import pandas as pd
import rasterio

LANDCOVER_DIR = "data/landcover"
TREE_COVER_CLASS = 10

_open_tiles: dict[str, rasterio.DatasetReader] = {}


def _tile_path(lat: float, lon: float) -> str:
    # ESA WorldCover tiles are 3x3 degrees, named by lower-left corner
    lat_tile = int(lat // 3) * 3
    lon_tile = int(lon // 3) * 3
    ns = "N" if lat_tile >= 0 else "S"
    ew = "E" if lon_tile >= 0 else "W"
    return f"{LANDCOVER_DIR}/{ns}{abs(lat_tile):02d}{ew}{abs(lon_tile):03d}.tif"


def sample_landcover(lat: float, lon: float) -> int:
    path = _tile_path(lat, lon)
    if path not in _open_tiles:
        _open_tiles[path] = rasterio.open(path)
    src = _open_tiles[path]
    row, col = src.index(lon, lat)
    row = min(max(row, 0), src.height - 1)
    col = min(max(col, 0), src.width - 1)
    # windowed single-pixel read -- this tile is 36000x36000 pixels, so
    # reading the full band per call (as before) was reloading ~1.3GB from
    # disk for every single lookup
    return int(src.read(1, window=((row, row + 1), (col, col + 1)))[0, 0])


def compute_tree_cover_pct(profile: pd.DataFrame) -> float:
    values = [
        sample_landcover(lat, lon) for lat, lon in zip(profile["lat"], profile["lon"])
    ]
    is_tree = [v == TREE_COVER_CLASS for v in values]
    return sum(is_tree) / len(is_tree) * 100
