import time
from collections import defaultdict

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import LineString

from recommender.pipeline.osm_trails import _GEOD, _merge_pieces

BASE_URL = "https://mapservices.nps.gov/arcgis/rest/services/NationalDatasets/NPS_Public_Trails_Geographic/FeatureServer/0/query"
PAGE_SIZE = 2000
WHERE = (
    "(UPPER(TRLUSE) LIKE '%HIK%' OR UPPER(TRLUSE) LIKE '%PEDESTRIAN%' "
    "OR UPPER(TRLUSE) LIKE '%WALK%' OR UPPER(TRLUSE) LIKE '%FOOT%') "
    "AND ISEXTANT<>'False'"
)
OUTPUT_PATH = "data/regions/nps_trails.parquet"

# NPS has no single per-trail id field (FEATUREID/GEOMETRYID are unique PER
# SEGMENT, verified empirically against Yosemite's Mist Trail -- 4 segments,
# 4 different ids each). (TRLNAME, UNITCODE) is used instead: unlikely to
# collide within one park, and UNITCODE (e.g. "YOSE") prevents the
# cross-park name collisions seen with USFS's trail_cn-less alternative
ID_OFFSET = 95_000_000_000


def fetch_all_segments() -> pd.DataFrame:
    rows = []
    offset = 0
    while True:
        params = {
            "where": WHERE,
            "outFields": "TRLNAME,UNITCODE",
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
                    "trail_name": attrs["TRLNAME"],
                    "unit_code": attrs["UNITCODE"],
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
        # pd.isna() is required here, not `not name` -- a NaN float is
        # truthy in Python (only 0.0 is falsy among floats), so `not name`
        # silently let missing names through, all landing in the same
        # ("nan", unit_code) group and merging into one fake 996km "trail"
        if pd.isna(name) or not str(name).strip():
            continue
        key = (str(name).strip(), row["unit_code"])
        for path in row["paths"]:
            if len(path) >= 2:
                grouped[key].append(LineString(path))

    rows = []
    skipped = 0
    for i, (key, pieces) in enumerate(grouped.items()):
        name, unit_code = key
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
    print("fetching NPS trail segments...")
    segments = fetch_all_segments()
    print(f"total segments fetched: {len(segments)}")

    print("grouping segments into trails by (name, park unit)...")
    trails_gdf = assemble_trails(segments)

    trails_gdf.to_parquet(OUTPUT_PATH)
    print(f"saved {len(trails_gdf)} trails to {OUTPUT_PATH}")
