import time
from collections import defaultdict

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import LineString

from recommender.pipeline.osm_trails import _GEOD, _merge_pieces

BASE_URL = "https://apps.fs.usda.gov/ArcX/rest/services/EDW/EDW_TrailNFSPublishWithDataStatus_01/MapServer/0/query"
PAGE_SIZE = 2000
WHERE = "trail_type='TERRA' AND terra_motorized<>'Y'"
OUTPUT_PATH = "data/regions/usfs_trails.parquet"

# USFS trail_cn values are strings (e.g. "5144.003871"), not usable directly
# as our integer osm_id -- offset well above any real OSM id (currently in
# the tens of millions) so there's no risk of collision
ID_OFFSET = 90_000_000_000


def fetch_all_segments() -> pd.DataFrame:
    rows = []
    offset = 0
    while True:
        params = {
            "where": WHERE,
            "outFields": "trail_cn,trail_name",
            "geometryPrecision": 6,
            "outSR": 4326,
            "resultOffset": offset,
            "resultRecordCount": PAGE_SIZE,
            "f": "json",
        }
        response = requests.get(BASE_URL, params=params, timeout=120)
        response.raise_for_status()
        data = response.json()
        features = data.get("features", [])
        if not features:
            break

        for feature in features:
            attrs = feature["attributes"]
            geometry = feature.get("geometry")
            if not geometry or not geometry.get("paths"):
                continue
            rows.append(
                {
                    "trail_cn": attrs["trail_cn"],
                    "trail_name": attrs["trail_name"],
                    "paths": geometry["paths"],
                }
            )

        print(f"  fetched {offset + len(features)} segments so far...")
        offset += PAGE_SIZE
        if not data.get("exceededTransferLimit", False) and len(features) < PAGE_SIZE:
            break
        time.sleep(0.2)  # light pacing -- a public government API, no need to hammer it

    return pd.DataFrame(rows)


def assemble_trails(segments: pd.DataFrame) -> gpd.GeoDataFrame:
    grouped = defaultdict(list)
    names = {}
    for _, row in segments.iterrows():
        cn = row["trail_cn"]
        names[cn] = row["trail_name"]
        for path in row["paths"]:
            if len(path) >= 2:
                grouped[cn].append(LineString(path))

    rows = []
    skipped = 0
    for i, (cn, pieces) in enumerate(grouped.items()):
        name = names[cn]
        if not name or not str(name).strip():
            skipped += 1
            continue
        distance_m = sum(abs(_GEOD.geometry_length(p)) for p in pieces)
        try:
            merged_geometry = _merge_pieces(pieces)
        except Exception:
            skipped += 1
            continue

        rows.append(
            {
                "osm_id": ID_OFFSET + i,
                "name": str(name).strip().title(),
                "distance_m": distance_m,
                "geometry": merged_geometry,
            }
        )

    print(f"assembled {len(rows)} trails, skipped {skipped}")
    return gpd.GeoDataFrame(rows, crs="EPSG:4326")


if __name__ == "__main__":
    print("fetching USFS trail segments...")
    segments = fetch_all_segments()
    print(f"total segments fetched: {len(segments)}")

    print("grouping segments into trails by trail_cn...")
    trails_gdf = assemble_trails(segments)

    trails_gdf.to_parquet(OUTPUT_PATH)
    print(f"saved {len(trails_gdf)} trails to {OUTPUT_PATH}")
