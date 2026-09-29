import os

import geopandas as gpd
import pandas as pd

# generous but real reduction from raw OSM/USFS/NPS/CA point density -- ~11m,
# imperceptible on a phone map at any zoom relevant to hiking, but already
# cuts point counts substantially before the API applies further,
# zoom-dependent simplification on top of this at request time
BASE_SIMPLIFY_TOLERANCE_DEG = 0.0001

REGION_FILES = [
    f"data/regions/{f}" for f in sorted(os.listdir("data/regions")) if f.endswith(".parquet")
]
OUTPUT_PATH = "data/trail_geometries.parquet"

if __name__ == "__main__":
    features = pd.read_parquet("data/trail_features.parquet", columns=["osm_id"])
    valid_osm_ids = set(features["osm_id"])
    print(f"valid trails (post-filter, in final catalog): {len(valid_osm_ids)}")

    all_trails = pd.concat([gpd.read_parquet(f) for f in REGION_FILES], ignore_index=True)
    all_trails = gpd.GeoDataFrame(all_trails, crs="EPSG:4326")
    all_trails = all_trails[all_trails["osm_id"].isin(valid_osm_ids)].reset_index(drop=True)
    print(f"matched geometries: {len(all_trails)}")

    all_trails["geometry"] = all_trails["geometry"].simplify(
        BASE_SIMPLIFY_TOLERANCE_DEG, preserve_topology=False
    )

    bounds = all_trails.geometry.bounds
    all_trails["minx"] = bounds["minx"]
    all_trails["miny"] = bounds["miny"]
    all_trails["maxx"] = bounds["maxx"]
    all_trails["maxy"] = bounds["maxy"]

    out = all_trails[["osm_id", "name", "distance_m", "minx", "miny", "maxx", "maxy", "geometry"]]
    out.to_parquet(OUTPUT_PATH)
    print(f"saved {len(out)} trail geometries to {OUTPUT_PATH}")
