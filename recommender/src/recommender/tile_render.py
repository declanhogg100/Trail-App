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
LANDCOVER_DIR = str(_PROJECT_ROOT / "data" / "landcover")

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



# ESA WorldCover ships as 3deg x 3deg tiles (vs. DEM's 1deg x 1deg), so the
# grid math is the same idea at a different cell size -- matches
# scan_needed_tiles.py's _landcover_tile_name, which is what determined
# which of these tiles actually got downloaded in the first place
def _landcover_paths_for_bbox(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> list[str]:
    paths = []
    lat_start, lat_end = math.floor(min_lat / 3) * 3, math.floor(max_lat / 3) * 3
    lon_start, lon_end = math.floor(min_lon / 3) * 3, math.floor(max_lon / 3) * 3
    for lat in range(lat_start, lat_end + 1, 3):
        for lon in range(lon_start, lon_end + 1, 3):
            ns, ew = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")
            path = f"{LANDCOVER_DIR}/{ns}{abs(lat):02d}{ew}{abs(lon):03d}.tif"
            if os.path.exists(path):
                paths.append(path)
    return paths


def _merge_clipped(paths: list[str], bounds: tuple[float, float, float, float], res: float | None = None):
    datasets = [rasterio.open(p) for p in paths]
    try:
        array, transform = merge(datasets, bounds=bounds, res=res, resampling=Resampling.nearest)
    finally:
        for d in datasets:
            d.close()
    return array[0].astype(np.float32), transform


# real elevation, shaded at literal 1:1 scale, reads as nearly flat gray
# for anything short of dramatic mountain terrain -- a 15m rise over a
# short trail is real and would be perfectly obvious on foot, but is far
# too subtle a gradient for a hillshade formula to make visible at screen
# resolution. Exaggerating elevation before shading is standard practice
# in terrain cartography for exactly this reason. Tuned so flatter trails
# (the common case) become genuinely readable without making already-steep
# mountain terrain look cartoonish -- the shading formula's own sin/cos
# terms saturate well before 255 on real slopes, so there's headroom.
VERTICAL_EXAGGERATION = 6.0


def _hillshade(elevation: np.ndarray, res_m: float) -> np.ndarray:
    dy, dx = np.gradient(elevation * VERTICAL_EXAGGERATION, max(res_m, 1.0))
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


# np.gradient has no visibility past an array's own edge (one-sided
# differences there), so computing it independently per tile -- each a
# standalone crop with no knowledge of its neighbors -- would leave visible
# seams where adjacent tiles' gradients don't quite agree along the shared
# border. Reprojecting a few extra pixels of margin on every side first,
# computing the gradient across that full padded array, and only then
# cropping back down to the real tile keeps every interior pixel's gradient
# identical to what it would be in the unbroken, un-tiled source.
GRADIENT_PAD_PX = 4


def _reproject_padded(src_array: np.ndarray, src_transform, dst_bounds_3857, resampling, dtype) -> np.ndarray:
    minx, miny, maxx, maxy = dst_bounds_3857
    res_x = (maxx - minx) / TILE_SIZE
    res_y = (maxy - miny) / TILE_SIZE
    padded_bounds = (
        minx - GRADIENT_PAD_PX * res_x,
        miny - GRADIENT_PAD_PX * res_y,
        maxx + GRADIENT_PAD_PX * res_x,
        maxy + GRADIENT_PAD_PX * res_y,
    )
    padded_size = TILE_SIZE + 2 * GRADIENT_PAD_PX
    dst_transform = rasterio.transform.from_bounds(*padded_bounds, padded_size, padded_size)
    dst = np.zeros((padded_size, padded_size), dtype=dtype)
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


# ESA WorldCover class codes -> muted, dark-theme-consistent colors.
# Deliberately desaturated -- an earlier version of this renderer used
# bright, saturated land-cover colors and it actively fought the trail
# route/walked-path line colors for attention on screen (see git history).
# These are meant to read as a subtle tint under the hillshade, not a
# colorful land-use map in their own right.
LANDCOVER_CLASS_COLORS: dict[int, tuple[int, int, int]] = {
    10: (45, 58, 42),  # tree cover
    20: (61, 63, 46),  # shrubland
    30: (74, 74, 53),  # grassland
    40: (74, 66, 48),  # cropland
    50: (58, 54, 54),  # built-up
    60: (74, 64, 56),  # bare / sparse vegetation
    70: (90, 90, 90),  # snow and ice
    80: (26, 38, 48),  # permanent water bodies
    90: (42, 58, 53),  # herbaceous wetland
    95: (42, 58, 53),  # mangroves
    100: (80, 80, 70),  # moss and lichen
}
# used for any class code not in the table above (there shouldn't be any,
# but better an unobtrusive fallback than a KeyError mid-render) and for
# tiles with no land-cover data at all (ocean far from shore, etc.)
LANDCOVER_DEFAULT_COLOR = (74, 63, 56)


def _tint_with_landcover(gray: np.ndarray, landcover: np.ndarray | None) -> np.ndarray:
    if landcover is None:
        return np.stack([gray, gray, gray], axis=-1)

    tint = np.full((*landcover.shape, 3), LANDCOVER_DEFAULT_COLOR, dtype=np.float32)
    landcover_int = np.round(landcover).astype(np.int16)
    for cls, color in LANDCOVER_CLASS_COLORS.items():
        mask = landcover_int == cls
        for c in range(3):
            tint[:, :, c] = np.where(mask, color[c], tint[:, :, c])

    # multiply blend -- the hillshade's own luminance (0-255) still carries
    # all the terrain shape/shading, the land-cover tint only recolors it,
    # it doesn't replace it with flat color regions. The 1.4 factor
    # compensates for multiply-blending otherwise darkening everything
    # (tint values are themselves well under 255), keeping the result close
    # to the tint's own intended brightness rather than uniformly dim.
    luminance = gray / 255.0
    return np.clip(tint * luminance[:, :, None] * 1.4, 0, 255)


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
    use_landcover: bool = True,
    landcover_res_deg: float | None = None,
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

    # land-cover is purely a visual tint on top of the hillshade -- unlike
    # the DEM above, its absence isn't fatal (some corners of the catalog
    # may not have it), it just falls back to the old pure-grayscale look.
    # landcover_res_deg downsamples the merge for wide, coarse renders
    # (CONTEXT_ZOOMS) -- at that scale individual 10m land-cover pixels
    # aren't visually meaningful anyway, and merging full-resolution
    # WorldCover data across a 12km buffer measured at ~230M pixels / ~3s
    # for one trail. A coarser merge keeps color consistent across the
    # whole map (no visible seam where the fine corridor's tint stops) at
    # a fraction of the cost -- leaving it a flat None for the fine render,
    # which is already fast at native resolution.
    landcover_paths = _landcover_paths_for_bbox(*clip_bounds) if use_landcover else []
    landcover, landcover_transform = (
        _merge_clipped(landcover_paths, clip_bounds, res=landcover_res_deg)
        if landcover_paths
        else (None, None)
    )

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

            # elevation (not the shaded result) is upsampled to this tile's
            # own fine grid first, and the hillshade gradient computed
            # *after* that -- computing it once on the source DEM's native
            # ~25-30m grid and only upsampling the shaded result afterward
            # left the coarse source grid's own blockiness visible (bilinear
            # smooths the transitions between cells, but doesn't add
            # resolution the gradient never had). Doing it per-tile is more
            # compute, but at these tile counts (tens, not thousands) that's
            # not a real cost. Reprojected with a few pixels of margin (see
            # GRADIENT_PAD_PX) and cropped back down after shading, so the
            # gradient at this tile's own edges isn't a one-sided guess.
            padded_elevation = _reproject_padded(
                elevation, dem_transform, dst_bounds, Resampling.bilinear, np.float32
            )
            # dst_bounds is already in Web Mercator meters, so the tile's
            # own resolution falls straight out of its extent -- no
            # degrees-to-meters approximation needed the way the old
            # single-pass version needed one for the source DEM's grid
            res_m = (dst_bounds[2] - dst_bounds[0]) / TILE_SIZE
            padded_shade = _hillshade(padded_elevation, res_m)
            shade_tile = padded_shade[GRADIENT_PAD_PX:-GRADIENT_PAD_PX, GRADIENT_PAD_PX:-GRADIENT_PAD_PX]
            gray = np.clip(shade_tile, 0, 255).astype(np.uint8)

            # land-cover reprojected with nearest-neighbor, not bilinear --
            # it's a categorical class code, not a continuous value, so
            # interpolating "between" classes would invent nonsense
            # intermediate values rather than just picking the nearer one
            landcover_tile = (
                _reproject_to_tile(landcover, landcover_transform, dst_bounds, Resampling.nearest, np.float32)
                if landcover is not None
                else None
            )
            composite = _tint_with_landcover(gray, landcover_tile).astype(np.uint8)
            results[(zoom, x, y)] = Image.fromarray(composite, mode="RGB")

    return results


# validated against a 6km mountain trail: 38 tiles / a few MB at this zoom
# range and buffer, vs. 404 tiles / ~21MB with an extra zoom level and no
# corridor filtering -- enough detail to follow the trail on foot without
# ballooning the download
OFFLINE_ZOOMS = [13, 14, 15]
OFFLINE_BUFFER_M = 600.0

# a second, much wider but coarser render -- lets the app lock its camera
# to (and let you zoom out to see) a real chunk of surrounding geography
# instead of either the narrow hiking corridor above or nothing at all.
# Cheap specifically because it's coarse: each tile at these zooms covers
# far more ground than one at OFFLINE_ZOOMS, so 12km of buffer here is a
# handful of tiles, not the hundreds it'd be at the fine zooms.
CONTEXT_ZOOMS = [10, 11, 12]
CONTEXT_BUFFER_M = 12_000.0


def render_trail_tiles(geometry: LineString | MultiLineString) -> dict[tuple[int, int, int], Image.Image]:
    corridor = _corridor_polygon(geometry, OFFLINE_BUFFER_M)
    min_lon, min_lat, max_lon, max_lat = corridor.bounds
    fine = render_tiles(min_lon, min_lat, max_lon, max_lat, OFFLINE_ZOOMS, corridor=corridor)

    context_corridor = _corridor_polygon(geometry, CONTEXT_BUFFER_M)
    c_min_lon, c_min_lat, c_max_lon, c_max_lat = context_corridor.bounds
    context = render_tiles(
        c_min_lon,
        c_min_lat,
        c_max_lon,
        c_max_lat,
        CONTEXT_ZOOMS,
        corridor=context_corridor,
        # ~55m/pixel -- plenty for CONTEXT_ZOOMS' own native resolution
        # (~38-150m/pixel across zooms 10-12), nowhere near WorldCover's
        # full 10m, which is what made this expensive in the first place
        landcover_res_deg=0.0005,
    )

    return {**fine, **context}
