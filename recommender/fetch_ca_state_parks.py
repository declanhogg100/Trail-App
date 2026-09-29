import time
from collections import defaultdict

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import LineString

from recommender.pipeline.osm_trails import _GEOD, _merge_pieces

BASE_URL = "https://services2.arcgis.com/AhxrK3F6WM8ECvDi/arcgis/rest/services/RecreationalRoutes/FeatureServer/0/query"
PAGE_SIZE = 2000
WHERE = "ROUTECLASS='State Park Trail' AND TRAILDES LIKE '%Hike%'"
OUTPUT_PATH = "data/regions/ca_state_parks_trails.parquet"

# GISID is unique PER SEGMENT (verified empirically against the "Wind
# Caves" trail -- 2 segments, 2 different GISIDs). UNITNAME is blank on
# almost every row, but UNITNBR is populated on all but 5 of 6942 rows, so
# (ROUTENAME, UNITNBR) is used instead, mirroring NPS's (TRLNAME, UNITCODE)
ID_OFFSET = 96_000_000_000

_UNNAMED = {"unamed", "unnamed"}


def fetch_all_segments() -> pd.DataFrame:
    rows = []
    offset = 0
    while True:
        params = {
            "where": WHERE,
            "outFields": "ROUTENAME,UNITNBR",
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
                    "trail_name": attrs["ROUTENAME"],
                    "unit_nbr": attrs["UNITNBR"],
                    "paths": geometry["paths"],
                }
            )

        print(f"  fetched {offset + len(features)} segments so far...")
        offset += PAGE_SIZE
        if not data.get("exceededTransferLimit", False) and len(features) < PAGE_SIZE:
            break
        time.sleep(0.2)

    return pd.DataFrame(rows)


def assemble_trails(segments: pd.DataFrame) -> gpd.GeoDataFrame:
    grouped = defaultdict(list)
    for _, row in segments.iterrows():
        name = row["trail_name"]
        # pd.isna() required, not `not name` -- NaN is truthy in Python
        # (see fetch_nps_trails.py for the bug this caused there)
        if pd.isna(name) or not str(name).strip():
            continue
        if str(name).strip().lower() in _UNNAMED:
            continue
        key = (str(name).strip(), row["unit_nbr"])
        for path in row["paths"]:
            if len(path) >= 2:
                grouped[key].append(LineString(path))

    rows = []
    skipped = 0
    for i, (key, pieces) in enumerate(grouped.items()):
        name, unit_nbr = key
        distance_m = sum(abs(_GEOD.geometry_length(p)) for p in pieces)
        try:
            merged_geometry = _merge_pieces(pieces)
        except Exception:
            skipped += 1
            continue

        rows.append(
            {
                "osm_id": ID_OFFSET + i,
                "name": name.title(),
                "distance_m": distance_m,
                "geometry": merged_geometry,
            }
        )

    print(f"assembled {len(rows)} trails, skipped {skipped}")
    return gpd.GeoDataFrame(rows, crs="EPSG:4326")


if __name__ == "__main__":
    print("fetching California State Parks trail segments...")
    segments = fetch_all_segments()
    print(f"total segments fetched: {len(segments)}")

    print("grouping segments into trails by (name, park unit)...")
    trails_gdf = assemble_trails(segments)

    trails_gdf.to_parquet(OUTPUT_PATH)
    print(f"saved {len(trails_gdf)} trails to {OUTPUT_PATH}")
