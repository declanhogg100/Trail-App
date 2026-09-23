import math
import os

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Geod

DEM_DIR = "data/dem"
LANDCOVER_DIR = "data/landcover"

_GEOD = Geod(ellps="WGS84")


def _dem_tile_name(lat: float, lon: float) -> str:
    lat_tile, lon_tile = math.floor(lat), math.floor(lon)
    ns = "N" if lat_tile >= 0 else "S"
    ew = "E" if lon_tile >= 0 else "W"
    return f"{ns}{abs(lat_tile):02d}{ew}{abs(lon_tile):03d}"


def _landcover_tile_name(lat: float, lon: float) -> str:
    lat_tile = int(lat // 3) * 3
    lon_tile = int(lon // 3) * 3
    ns = "N" if lat_tile >= 0 else "S"
    ew = "E" if lon_tile >= 0 else "W"
    return f"{ns}{abs(lat_tile):02d}{ew}{abs(lon_tile):03d}"


def _walk_points(line, step_m=90.0):
    # mirrors resample_elevation_profile's interpolation, but only yields
    # (lat, lon) -- no raster reads, so it never crashes on a missing tile
    coords = list(line.coords)
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    cum = [0.0]
    for i in range(1, len(coords)):
        _, _, dist = _GEOD.inv(lons[i - 1], lats[i - 1], lons[i], lats[i])
        cum.append(cum[-1] + dist)
    total = cum[-1]
    marks = np.arange(0, total, step_m)
    rlon = np.interp(marks, cum, lons)
    rlat = np.interp(marks, cum, lats)
    return zip(rlat, rlon)


def needed_tiles(all_trails: gpd.GeoDataFrame) -> tuple[set, set]:
    dem_tiles, landcover_tiles = set(), set()
    for geom in all_trails["geometry"]:
        pieces = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
        for piece in pieces:
            for lat, lon in _walk_points(piece):
                dem_tiles.add(_dem_tile_name(lat, lon))
                landcover_tiles.add(_landcover_tile_name(lat, lon))
    return dem_tiles, landcover_tiles


if __name__ == "__main__":
    region_files = [f"data/regions/{f}" for f in os.listdir("data/regions") if f.endswith(".parquet")]
    all_trails = pd.concat([gpd.read_parquet(f) for f in region_files], ignore_index=True)
    all_trails = gpd.GeoDataFrame(all_trails, crs="EPSG:4326")
    print(f"scanning {len(all_trails)} trails across {len(region_files)} regions...")

    dem_tiles, landcover_tiles = needed_tiles(all_trails)

    have_dem = {f.removesuffix(".tif") for f in os.listdir(DEM_DIR)}
    have_landcover = {f.removesuffix(".tif") for f in os.listdir(LANDCOVER_DIR)}

    missing_dem = sorted(dem_tiles - have_dem)
    missing_landcover = sorted(landcover_tiles - have_landcover)

    print(f"DEM tiles needed: {len(dem_tiles)}, missing: {len(missing_dem)}")
    print(missing_dem)
    print(f"land-cover tiles needed: {len(landcover_tiles)}, missing: {len(missing_landcover)}")
    print(missing_landcover)
