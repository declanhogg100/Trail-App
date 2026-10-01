import math
import os
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.merge import merge
from rasterio.warp import Resampling, reproject
from shapely.geometry import LineString, MultiLineString, box

# absolute, resolved from this file's own location -- not relative to the
# process's working directory. build_features.py and friends are always run
# by hand from within recommender/, so a relative path happens to work
# there, but this module is also imported by the API process (which runs
# from a different directory entirely), where a bare "data/dem" silently
# resolves to nowhere and every lookup below comes back empty.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEM_DIR = str(_PROJECT_ROOT / "data" / "dem")

# standard Web Mercator (EPSG:3857) slippy-map tile scheme -- same one
# OSM/Google/Apple all use, which is why every off-the-shelf map client
# (including MapLibre) expects tiles addressed this way by default
EARTH_RADIUS_M = 6378137.0
ORIGIN_SHIFT_M = math.pi * EARTH_RADIUS_M
TILE_SIZE = 256

def lonlat_to_tile(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    n = 2**zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def tiles_for_bbox(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float, zoom: int
) -> list[tuple[int, int]]:
    # tile y increases southward (tile (0,0) is the NW corner of the world),
    # the opposite direction from latitude -- so the NW corner of the bbox
    # gives the min x/y and the SE corner gives the max x/y, not the other
    # way around
    x_min, y_min = lonlat_to_tile(min_lon, max_lat, zoom)
    x_max, y_max = lonlat_to_tile(max_lon, min_lat, zoom)
    return [(x, y) for x in range(x_min, x_max + 1) for y in range(y_min, y_max + 1)]


def tile_bounds_3857(zoom: int, x: int, y: int) -> tuple[float, float, float, float]:
    res = (2 * ORIGIN_SHIFT_M) / TILE_SIZE / (2**zoom)
    tile_size_m = TILE_SIZE * res
    minx = x * tile_size_m - ORIGIN_SHIFT_M
    maxx = (x + 1) * tile_size_m - ORIGIN_SHIFT_M
    maxy = ORIGIN_SHIFT_M - y * tile_size_m
    miny = ORIGIN_SHIFT_M - (y + 1) * tile_size_m
    return minx, miny, maxx, maxy


def _mercator_to_lonlat(mx: float, my: float) -> tuple[float, float]:
    lon = mx / ORIGIN_SHIFT_M * 180.0
    lat = math.degrees(2 * math.atan(math.exp(my / ORIGIN_SHIFT_M * math.pi)) - math.pi / 2)
    return lon, lat


def _grid_bounds_lonlat(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float, zoom: int, pad_tiles: int = 0
) -> tuple[float, float, float, float]:
    # the tile grid's cells don't align with an arbitrary bbox -- snapping
    # out to the full extent of every tile that bbox touches (at the
    # coarsest zoom that will be rendered) guarantees every tile at every
    # finer zoom is fully covered too, since each is a strict subdivision
    # of a coarser one in this scheme. pad_tiles widens that by whole extra
    # tiles on each side -- used to fetch a safety margin of source data
    # beyond what's strictly needed, see render_tiles.
    tiles = tiles_for_bbox(min_lon, min_lat, max_lon, max_lat, zoom)
    xs = [x for x, _ in tiles]
    ys = [y for _, y in tiles]
    left, bottom, _, _ = tile_bounds_3857(zoom, min(xs) - pad_tiles, max(ys) + pad_tiles)
    _, _, right, top = tile_bounds_3857(zoom, max(xs) + pad_tiles, min(ys) - pad_tiles)
    lon_min, lat_min = _mercator_to_lonlat(left, bottom)
    lon_max, lat_max = _mercator_to_lonlat(right, top)
    return lon_min, lat_min, lon_max, lat_max


def _dem_paths_for_bbox(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> list[str]:
    paths = []
    for lat in range(math.floor(min_lat), math.floor(max_lat) + 1):
        for lon in range(math.floor(min_lon), math.floor(max_lon) + 1):
            ns, ew = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")
            path = f"{DEM_DIR}/{ns}{abs(lat):02d}{ew}{abs(lon):03d}.tif"
            if os.path.exists(path):
                paths.append(path)
    return paths



def _merge_clipped(paths: list[str], bounds: tuple[float, float, float, float]):
    datasets = [rasterio.open(p) for p in paths]
    try:
        array, transform = merge(datasets, bounds=bounds)
    finally:
        for d in datasets:
            d.close()
    return array[0].astype(np.float32), transform


def _hillshade(elevation: np.ndarray, px_size_deg: float, center_lat: float) -> np.ndarray:
    # approximate meters-per-pixel at this buffer's latitude -- good enough
    # for a background relief shade, not meant to be survey-grade
    m_per_deg = 111_320.0 * math.cos(math.radians(center_lat))
    res_m = max(px_size_deg * m_per_deg, 1.0)

    dy, dx = np.gradient(elevation, res_m)
    slope = math.pi / 2 - np.arctan(np.hypot(dx, dy))
    aspect = np.arctan2(-dx, dy)

    azimuth_rad = math.radians(360.0 - 315.0 + 90.0)
    altitude_rad = math.radians(45.0)
    shaded = np.sin(altitude_rad) * np.sin(slope) + np.cos(altitude_rad) * np.cos(slope) * np.cos(
        azimuth_rad - aspect
    )
    return np.clip(shaded * 255.0, 0, 255)


def _reproject_to_tile(src_array: np.ndarray, src_transform, dst_bounds_3857, resampling, dtype) -> np.ndarray:
    dst_transform = rasterio.transform.from_bounds(*dst_bounds_3857, TILE_SIZE, TILE_SIZE)
    dst = np.zeros((TILE_SIZE, TILE_SIZE), dtype=dtype)
    reproject(
        source=src_array,
        destination=dst,
        src_transform=src_transform,
        src_crs="EPSG:4326",
        dst_transform=dst_transform,
        dst_crs="EPSG:3857",
        resampling=resampling,
    )
    return dst


def _corridor_polygon(geometry: LineString | MultiLineString, buffer_m: float):
    # approximate degrees-per-meter at this geometry's latitude -- fine for
    # a visual download-corridor margin, not a survey measurement. Buffering
    # in plain lon/lat (rather than reprojecting to a metric CRS first) is
    # the same tradeoff already made elsewhere in this codebase for
    # similarly small, local buffers.
    _, min_lat, _, max_lat = geometry.bounds
    center_lat = (min_lat + max_lat) / 2
    buffer_deg = buffer_m / (111_320.0 * max(math.cos(math.radians(center_lat)), 0.1))
    return geometry.buffer(buffer_deg)


def render_tiles(
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    zooms: list[int],
    corridor=None,
) -> dict[tuple[int, int, int], Image.Image]:
    # clip source data to the full tile-grid extent at the coarsest zoom
    # being rendered, not the raw requested bbox -- see _grid_bounds_lonlat.
    # tile_bounds (unpadded) is what's actually enumerated/rendered;
    # clip_bounds adds a full extra tile of margin on every side purely for
    # the source-data fetch, since rasterio's merge(bounds=...) snaps its
    # output to the source raster's own pixel grid, which can fall a
    # fraction of a pixel short of the exact requested max edge -- without
    # this margin, tiles along the far (east/south) edge come out with a
    # thin strip of missing data. A whole tile of slack is generous on
    # purpose: cheap to fetch, and immune to how large that rounding
    # shortfall turns out to be at any given zoom.
    tile_bounds = _grid_bounds_lonlat(min_lon, min_lat, max_lon, max_lat, min(zooms))
    clip_bounds = _grid_bounds_lonlat(min_lon, min_lat, max_lon, max_lat, min(zooms), pad_tiles=1)

    dem_paths = _dem_paths_for_bbox(*clip_bounds)
    if not dem_paths:
        raise ValueError(f"no source tiles available for bbox {clip_bounds}")

    elevation, dem_transform = _merge_clipped(dem_paths, clip_bounds)

    center_lat = (clip_bounds[1] + clip_bounds[3]) / 2
    hillshade = _hillshade(elevation, abs(dem_transform.a), center_lat)

    results: dict[tuple[int, int, int], Image.Image] = {}
    for zoom in zooms:
        for x, y in tiles_for_bbox(*tile_bounds, zoom):
            dst_bounds = tile_bounds_3857(zoom, x, y)

            if corridor is not None:
                # keep downloads proportional to the trail's actual length,
                # not its bounding box's area -- a long, winding, or
                # L-shaped trail can have a bbox far bigger than the ground
                # it actually covers (the PCT is the extreme case), and
                # rendering that whole rectangle would balloon the download
                lon_w, lat_s = _mercator_to_lonlat(dst_bounds[0], dst_bounds[1])
                lon_e, lat_n = _mercator_to_lonlat(dst_bounds[2], dst_bounds[3])
                if not corridor.intersects(box(lon_w, lat_s, lon_e, lat_n)):
                    continue

            # pure grayscale shaded relief -- no land-cover color at all, by
            # design: a busy multi-hue background was actively fighting the
            # trail/walked-path line colors for attention on a screen whose
            # whole job is making that line easy to follow. The hillshade
            # value IS the pixel value directly (R=G=B), no compositing.
            shade_tile = _reproject_to_tile(hillshade, dem_transform, dst_bounds, Resampling.bilinear, np.float32)
            gray = np.clip(shade_tile, 0, 255).astype(np.uint8)
            composite = np.stack([gray, gray, gray], axis=-1)
            results[(zoom, x, y)] = Image.fromarray(composite, mode="RGB")

    return results


# validated against a 6km mountain trail: 38 tiles / a few MB at this zoom
# range and buffer, vs. 404 tiles / ~21MB with an extra zoom level and no
# corridor filtering -- enough detail to follow the trail on foot without
# ballooning the download
OFFLINE_ZOOMS = [13, 14, 15]
OFFLINE_BUFFER_M = 600.0


def render_trail_tiles(geometry: LineString | MultiLineString) -> dict[tuple[int, int, int], Image.Image]:
    corridor = _corridor_polygon(geometry, OFFLINE_BUFFER_M)
    min_lon, min_lat, max_lon, max_lat = corridor.bounds
    return render_tiles(min_lon, min_lat, max_lon, max_lat, OFFLINE_ZOOMS, corridor=corridor)
