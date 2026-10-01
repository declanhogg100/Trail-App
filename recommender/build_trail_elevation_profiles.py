import os

import geopandas as gpd
import pandas as pd

from recommender.pipeline.elevation import resample_trail

REGION_FILES = [
    f"data/regions/{f}" for f in sorted(os.listdir("data/regions")) if f.endswith(".parquet")
]
OUTPUT_PATH = "data/trail_elevation_profiles.parquet"

# matches the resolution time_estimator's own training data was resampled at
# (time_estimator/pipeline/parse_gpx.py's resample_by_distance default) --
# the GRU model expects profiles at roughly this same point density
STEP_M = 40.0


def build_profile(geometry) -> pd.DataFrame:
    pieces = resample_trail(geometry, step_m=STEP_M)

    # a MultiLineString trail (a gap in the source data) still needs ONE
    # continuous, increasing distance axis to feed the model -- each
    # piece's distance picks up where the previous one left off, rather
    # than resetting to 0 and producing a bogus non-monotonic sequence
    offset = 0.0
    combined = []
    for piece in pieces:
        piece = piece.copy()
        piece["distance_m"] = piece["distance_m"] + offset
        offset = piece["distance_m"].iloc[-1]
        combined.append(piece)
    return pd.concat(combined, ignore_index=True)


if __name__ == "__main__":
    features = pd.read_parquet("data/trail_features.parquet", columns=["osm_id"])
    valid_osm_ids = set(features["osm_id"])
    print(f"valid trails (post-filter, in final catalog): {len(valid_osm_ids)}")

    all_trails = pd.concat([gpd.read_parquet(f) for f in REGION_FILES], ignore_index=True)
    all_trails = gpd.GeoDataFrame(all_trails, crs="EPSG:4326")
    all_trails = all_trails[all_trails["osm_id"].isin(valid_osm_ids)].reset_index(drop=True)
    print(f"matched geometries: {len(all_trails)}")

    rows = []
    failed = []
    for _, trail in all_trails.iterrows():
        try:
            profile = build_profile(trail["geometry"])
        except Exception as e:
            failed.append((trail["osm_id"], trail["name"], f"{type(e).__name__}: {e}"))
            continue
        rows.append(
            {
                "osm_id": trail["osm_id"],
                "distance_m": profile["distance_m"].tolist(),
                "elevation": profile["elevation"].tolist(),
            }
        )

    print(f"built profiles for {len(rows)} trails")
    print(f"failed: {len(failed)}")
    for osm_id, name, err in failed:
        print(f"  {name} ({osm_id}): {err}")

    pd.DataFrame(rows).to_parquet(OUTPUT_PATH, index=False)
    print(f"saved to {OUTPUT_PATH}")
