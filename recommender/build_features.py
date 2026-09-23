import os

import geopandas as gpd
import pandas as pd

from recommender.pipeline.features import compute_trail_features

REGION_FILES = [
    f"data/regions/{f}" for f in sorted(os.listdir("data/regions")) if f.endswith(".parquet")
]

all_trails = pd.concat([gpd.read_parquet(f) for f in REGION_FILES], ignore_index=True)
all_trails = gpd.GeoDataFrame(all_trails, crs="EPSG:4326")

MIN_DISTANCE_M = 500
before = len(all_trails)
all_trails = all_trails[all_trails["distance_m"] >= MIN_DISTANCE_M].reset_index(drop=True)
print(f"dropped {before - len(all_trails)} trails under {MIN_DISTANCE_M}m (via ferratas, hut spurs, connectors)")
print(f"total trails: {len(all_trails)}")

rows = []
failed = []
for _, trail in all_trails.iterrows():
    try:
        rows.append(compute_trail_features(trail))
    except Exception as e:
        failed.append((trail["osm_id"], trail["name"], f"{type(e).__name__}: {e}"))

features_df = pd.DataFrame(rows)
print(f"computed features for {len(features_df)} trails")
print(f"failed: {len(failed)}")
for osm_id, name, err in failed:
    print(f"  {name} ({osm_id}): {err}")

features_df.to_parquet("data/trail_features.parquet", index=False)
print("saved to data/trail_features.parquet")
