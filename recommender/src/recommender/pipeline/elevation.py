import numpy as np
import pandas as pd
import rasterio
from pyproj import Geod
from shapely.geometry import LineString, MultiLineString

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
    # read just this one pixel via a window, not the whole band -- reading
    # the full array here would re-load the entire tile from disk on every
    # single call
    return float(src.read(1, window=((row, row + 1), (col, col + 1)))[0, 0])


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


def _local_extreme_elevation(
    lat: float, lon: float, search_radius_px: int = 2, find_max: bool = True
) -> tuple[float, float, float]:
    path = _tile_path(lat, lon)
    if path not in _open_tiles:
        _open_tiles[path] = rasterio.open(path)
    src = _open_tiles[path]

    
    center_row, center_col = src.index(lon, lat)
    row_start = max(center_row - search_radius_px, 0)
    col_start = max(center_col - search_radius_px, 0)
    row_stop = min(center_row + search_radius_px, src.height - 1)
    col_stop = min(center_col + search_radius_px, src.width - 1)

    window = src.read(1, window=((row_start, row_stop + 1), (col_start, col_stop + 1)))

    idx = np.unravel_index(window.argmax() if find_max else window.argmin(), window.shape)
    extreme_row = row_start + idx[0]
    extreme_col = col_start + idx[1]
    extreme_elevation = float(window[idx])

    extreme_lon, extreme_lat = src.xy(extreme_row, extreme_col)
    return extreme_lat, extreme_lon, extreme_elevation


def compute_prominence_features(profile: pd.DataFrame) -> dict:
    trail_peak = profile.loc[profile["elevation"].idxmax()]
    trail_low = profile.loc[profile["elevation"].idxmin()]

    # the trail's own resampled points might land slightly off the true
    # nearby high/low point -- refine with a small local search before
    # measuring against the (much larger radius) surrounding terrain
    peak_lat, peak_lon, peak_elev = _local_extreme_elevation(
        trail_peak["lat"], trail_peak["lon"], find_max=True
    )
    low_lat, low_lon, low_elev = _local_extreme_elevation(
        trail_low["lat"], trail_low["lon"], find_max=False
    )

    peak_surrounding = sample_surrounding_elevation(peak_lat, peak_lon)
    low_surrounding = sample_surrounding_elevation(low_lat, low_lon)

    return {
        "peak_elevation_m": peak_elev,
        "peak_prominence_m": peak_elev - peak_surrounding,
        "low_elevation_m": low_elev,
        "low_relative_m": low_elev - low_surrounding,
    }


def resample_trail(
    geometry: LineString | MultiLineString, step_m: float = 90.0
) -> list[pd.DataFrame]:
    # always return a list of per-piece profiles, even for a single
    # LineString (a list of one) -- keeps every caller consistent whether
    # or not a trail fully merged into one continuous line
    pieces = geometry.geoms if geometry.geom_type == "MultiLineString" else [geometry]
    return [resample_elevation_profile(piece, step_m) for piece in pieces]


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
    # always include the true endpoint -- otherwise the final partial
    # segment (< step_m) is silently dropped for every trail, and trails
    # shorter than step_m end up with only a single sample point (making
    # grade variability undefined, since there's no second point to diff against)
    if total_distance > 0 and (len(distance_marks) == 0 or distance_marks[-1] < total_distance):
        distance_marks = np.append(distance_marks, total_distance)

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


def compute_gain_and_grade_stats(profiles: list[pd.DataFrame]) -> dict:
    total_gain_m = 0.0
    all_grades = []

    for profile in profiles:
        elevation = profile["elevation"].to_numpy()
        distance = profile["distance_m"].to_numpy()

        # diff *within* this piece only -- never across a gap between
        # separate pieces, same principle as the GPX segment-boundary fix
        rise = np.diff(elevation)
        run = np.diff(distance)

        total_gain_m += rise[rise > 0].sum()
        all_grades.append(rise / run)

    # pool every piece's grade values together before taking the std, so a
    # trail's variability reflects its whole length, not an average of
    # per-piece averages (which would understate variability between pieces)
    pooled_grades = np.concatenate(all_grades)

    return {
        "elevation_gain_m": float(total_gain_m),
        "grade_std": float(np.std(pooled_grades)),
    }
