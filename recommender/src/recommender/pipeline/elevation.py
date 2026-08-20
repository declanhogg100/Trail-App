import numpy as np
import pandas as pd
import rasterio
from pyproj import Geod
from shapely.geometry import LineString

DEM_DIR = "data/dem"
_GEOD = Geod(ellps="WGS84")

_open_tiles: dict[str, rasterio.DatasetReader] = {}


def _tile_path(lat: float, lon: float) -> str:
    lat_tile = int(lat // 1)
    lon_tile = int(lon // 1)
    ns = "N" if lat_tile >= 0 else "S"
    ew = "E" if lon_tile >= 0 else "W"
    return f"{DEM_DIR}/{ns}{abs(lat_tile):02d}{ew}{abs(lon_tile):03d}.tif"


def sample_elevation(lat: float, lon: float) -> float:
    path = _tile_path(lat, lon)
    if path not in _open_tiles:
        _open_tiles[path] = rasterio.open(path)
    src = _open_tiles[path]
    row, col = src.index(lon, lat)
    # a point sitting exactly on a tile's outer edge can map to one index
    # past the last valid pixel -- clamp back into bounds rather than crash
    row = min(max(row, 0), src.height - 1)
    col = min(max(col, 0), src.width - 1)
    return float(src.read(1)[row, col])


METERS_PER_DEGREE_LAT = 111_320


def sample_surrounding_elevation(lat: float, lon: float, radius_m: float = 3000.0) -> float:
    path = _tile_path(lat, lon)
    if path not in _open_tiles:
        _open_tiles[path] = rasterio.open(path)
    src = _open_tiles[path]

    meters_per_degree_lon = METERS_PER_DEGREE_LAT * np.cos(np.radians(lat))
    lat_buffer_deg = radius_m / METERS_PER_DEGREE_LAT
    lon_buffer_deg = radius_m / meters_per_degree_lon

    # window covering a square bounding box around the point -- note this
    # is only correct for radii well within a single DEM tile; a radius
    # crossing a tile boundary would silently clamp rather than pull in
    # the neighboring tile
    row_start, col_start = src.index(lon - lon_buffer_deg, lat + lat_buffer_deg)
    row_stop, col_stop = src.index(lon + lon_buffer_deg, lat - lat_buffer_deg)
    row_start = max(row_start, 0)
    col_start = max(col_start, 0)
    row_stop = min(row_stop, src.height - 1)
    col_stop = min(col_stop, src.width - 1)

    window = src.read(1, window=((row_start, row_stop + 1), (col_start, col_stop + 1)))

    center_row, center_col = src.index(lon, lat)
    xres, yres = src.res
    rows = np.arange(row_start, row_stop + 1)
    cols = np.arange(col_start, col_stop + 1)
    col_grid, row_grid = np.meshgrid(cols, rows)

    # per-pixel distance from center, in meters -- a local flat-earth
    # approximation, fine at this radius (a few km) but not for anything
    # large enough for Earth's curvature to matter
    dy_m = (row_grid - center_row) * yres * METERS_PER_DEGREE_LAT
    dx_m = (col_grid - center_col) * xres * meters_per_degree_lon
    dist_m = np.sqrt(dx_m**2 + dy_m**2)

    # restrict to an actual circle, not the whole square window
    circle_mask = dist_m <= radius_m
    return float(window[circle_mask].mean())


def resample_elevation_profile(line: LineString, step_m: float = 90.0) -> pd.DataFrame:
    coords = list(line.coords)
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]

    # geodesic distance along the line -- purely horizontal, since OSM
    # geometry has no elevation baked in (unlike the GPX 3D-distance case,
    # there's no hypotenuse/run correction needed here)
    cumulative_distance_m = [0.0]
    for i in range(1, len(coords)):
        _, _, dist = _GEOD.inv(lons[i - 1], lats[i - 1], lons[i], lats[i])
        cumulative_distance_m.append(cumulative_distance_m[-1] + dist)

    total_distance = cumulative_distance_m[-1]
    distance_marks = np.arange(0, total_distance, step_m)

    resampled_lon = np.interp(distance_marks, cumulative_distance_m, lons)
    resampled_lat = np.interp(distance_marks, cumulative_distance_m, lats)
    elevations = [
        sample_elevation(lat, lon) for lat, lon in zip(resampled_lat, resampled_lon)
    ]

    return pd.DataFrame(
        {
            "distance_m": distance_marks,
            "lon": resampled_lon,
            "lat": resampled_lat,
            "elevation": elevations,
        }
    )


def compute_gain_and_grade_stats(profile: pd.DataFrame) -> dict:
    elevation = profile["elevation"].to_numpy()
    distance = profile["distance_m"].to_numpy()

    rise = np.diff(elevation)
    run = np.diff(distance)

    gain_m = rise[rise > 0].sum()
    grade = rise / run

    return {
        "elevation_gain_m": float(gain_m),
        "grade_std": float(np.std(grade)),
    }
