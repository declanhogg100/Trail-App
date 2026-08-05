import time

from time_estimator.pipeline.hikr_dataset import build_segment_dataset, filter_valid_hikes, load_hikr_csv

df = load_hikr_csv("data/hikr/gpx-tracks-from-hikr.org.csv")
clean = filter_valid_hikes(df)

print("---")
start = time.time()
segments_df, failed_ids = build_segment_dataset(clean)
elapsed = time.time() - start
print(f"processed {len(clean)} hikes in {elapsed:.1f}s")
print(f"failed to parse: {len(failed_ids)}")
print(f"total segments: {len(segments_df)}")

hikes_df = clean.drop(columns=["gpx"]).rename(columns={"_id": "hike_id"})
hikes_df = hikes_df[~hikes_df["hike_id"].isin(failed_ids)]
print(f"dropped {len(failed_ids)} hikes with no segments; hikes_df now {len(hikes_df)} rows")

segments_df.to_parquet("data/hikr/segments.parquet", index=False)
hikes_df.to_parquet("data/hikr/hikes.parquet", index=False)

print("---")
print("saved data/hikr/segments.parquet and data/hikr/hikes.parquet")
