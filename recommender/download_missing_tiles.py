import os

from fetch_tiles import dem_url, download, landcover_url
from scan_needed_tiles import needed_tiles
import geopandas as gpd
import pandas as pd

region_files = [f"data/regions/{f}" for f in os.listdir("data/regions") if f.endswith(".parquet")]
all_trails = pd.concat([gpd.read_parquet(f) for f in region_files], ignore_index=True)
all_trails = gpd.GeoDataFrame(all_trails, crs="EPSG:4326")
print(f"scanning {len(all_trails)} trails across {len(region_files)} regions...")

dem_tiles, landcover_tiles = needed_tiles(all_trails)

have_dem = {f.removesuffix(".tif") for f in os.listdir("data/dem")}
have_landcover = {f.removesuffix(".tif") for f in os.listdir("data/landcover")}

missing_dem = sorted(dem_tiles - have_dem)
missing_landcover = sorted(landcover_tiles - have_landcover)

print(f"downloading {len(missing_dem)} DEM tiles...")
for tile in missing_dem:
    print(f"fetching {tile}...")
    try:
        download(dem_url(tile), f"data/dem/{tile}.tif")
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")

print(f"downloading {len(missing_landcover)} land-cover tiles...")
for tile in missing_landcover:
    print(f"fetching {tile}...")
    try:
        download(landcover_url(tile), f"data/landcover/{tile}.tif")
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")

print("---")
print("done")
