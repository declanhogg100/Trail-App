import os
import time

from recommender.pipeline.osm_trails import fetch_hiking_relations, relations_to_geodataframe

REGIONS = {
    "zermatt": (7.60, 45.95, 7.85, 46.10),
    "joshua_tree": (-116.458031, 33.6701858, -115.2621906, 34.129343),
    "olympic_np": (-124.7425886, 47.4697688, -123.1240183, 48.2752636),
    "cinque_terre": (9.6153716, 44.0638062, 9.8071243, 44.1854747),
    "yosemite": (-119.8861599, 37.4921493, -119.1995075, 38.1863499),
    "glencoe": (-5.2514552, 56.5827647, -4.9514552, 56.7827647),
    "torres_del_paine": (-73.3, -51.3, -72.5, -50.8),
    "jotunheimen": (8.0, 61.35, 8.8, 61.75),
    "annapurna": (83.7, 28.3, 84.2, 28.9),
    "atlas_mountains": (-8.1, 30.9, -7.7, 31.25),
    "drakensberg": (28.9, -29.3, 29.5, -28.6),
    "fiordland": (167.3, -45.5, 168.3, -44.6),
    "julian_alps": (13.7, 46.3, 14.1, 46.5),
    "tatra_mountains": (19.85, 49.15, 20.2, 49.3),
    "peak_district": (-1.9, 53.2, -1.5, 53.45),
    "monteverde": (-84.95, 10.25, -84.7, 10.45),
    "rocky_mountain_np": (-105.85, 40.15, -105.5, 40.55),
    "zion": (-113.15, 37.1, -112.8, 37.45),
    "dolomites": (11.8, 46.4, 12.4, 46.7),
    "chamonix": (6.75, 45.85, 7.05, 45.99),
    "sierra_nevada_spain": (-3.5, 36.9, -3.0, 37.15),
    "lake_district": (-3.3, 54.35, -2.9, 54.65),
    "snowdonia": (-4.15, 52.9, -3.85, 53.15),
    "banff": (-116.3, 51.1, -115.5, 51.5),
}

PAUSE_BETWEEN_REQUESTS_S = 10

for name, bbox in REGIONS.items():
    out_path = f"data/regions/{name}.parquet"
    if os.path.exists(out_path):
        print(f"skipping {name}, already fetched")
        continue
    try:
        print(f"fetching {name}...")
        data = fetch_hiking_relations(bbox)
        gdf = relations_to_geodataframe(data)
        gdf.to_parquet(out_path)
        print(f"  saved {len(gdf)} trails to {out_path}")
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {e}")

    time.sleep(PAUSE_BETWEEN_REQUESTS_S)

print("---")
print("done")
