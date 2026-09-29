import re

import geopandas as gpd
import pandas as pd

INPUT_PATH = "data/regions/ca_state_parks_trails.parquet"
OUTPUT_PATH = "data/regions/ca_state_parks_trails.parquet"
MAX_DIST_M = 2000

_STOPWORDS = re.compile(r"\b(trail|trl|path|route|rd|road)\b")


def normalize_name(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    name = _STOPWORDS.sub("", name)
    return re.sub(r"\s+", " ", name).strip()


if __name__ == "__main__":
    print("loading existing catalog (OSM + USFS + NPS)...")
    existing = pd.concat(
        [
            gpd.read_parquet("data/regions/us_national.parquet")[["osm_id", "name", "geometry"]],
            gpd.read_parquet("data/regions/usfs_trails.parquet")[["osm_id", "name", "geometry"]],
            gpd.read_parquet("data/regions/nps_trails.parquet")[["osm_id", "name", "geometry"]],
        ],
        ignore_index=True,
    )
    existing = gpd.GeoDataFrame(existing, crs="EPSG:4326")

    ca = gpd.read_parquet(INPUT_PATH)
    print(f"CA State Parks trails before dedup: {len(ca)}")

    # restrict candidates to CA's bounding box (+ buffer) for speed
    minx, miny, maxx, maxy = ca.total_bounds
    buf = 0.5
    existing_ca = existing.cx[minx - buf : maxx + buf, miny - buf : maxy + buf]

    existing_ca = existing_ca.to_crs("EPSG:5070")
    ca_proj = ca.to_crs("EPSG:5070")
    existing_ca["norm_name"] = existing_ca["name"].apply(normalize_name)
    ca_proj["norm_name"] = ca_proj["name"].apply(normalize_name)

    joined = gpd.sjoin_nearest(
        ca_proj, existing_ca, max_distance=MAX_DIST_M, distance_col="dist_m", how="left"
    )

    # a CA trail is a duplicate if ANY nearby (<=2km) existing trail shares
    # its normalized name -- proximity alone isn't enough (many parks have
    # multiple unrelated trails within 2km of each other)
    is_dup = joined["norm_name_left"] == joined["norm_name_right"]
    dup_osm_ids = set(joined.loc[is_dup, "osm_id_left"])

    deduped = ca[~ca["osm_id"].isin(dup_osm_ids)].reset_index(drop=True)
    print(f"duplicates dropped: {len(dup_osm_ids)}")
    print(f"CA State Parks trails after dedup: {len(deduped)}")

    deduped.to_parquet(OUTPUT_PATH)
    print(f"saved to {OUTPUT_PATH}")
