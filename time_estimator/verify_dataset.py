from time_estimator.pipeline.dataset import collate_trails
from time_estimator.pipeline.parse_gpx import compute_grade, load_gpx_points, resample_by_distance

df = load_gpx_points("data/raw/Mojstrovka.gpx")
resampled = compute_grade(resample_by_distance(df, step_m=40.0))

# no second real trail yet -- fake a shorter one by truncating, just to exercise padding
short_trail = resampled.iloc[:40].reset_index(drop=True)
long_trail = resampled

padded, lengths = collate_trails([short_trail, long_trail])

print(f"short trail length: {len(short_trail)}")
print(f"long trail length: {len(long_trail)}")
print(f"padded batch shape: {padded.shape}")
print(f"lengths tensor: {lengths}")
print("---")
print("short trail, last 5 rows of padded tensor (should be zeros):")
print(padded[0, -5:])
print("---")
print("long trail, last 5 rows of padded tensor (should be real data, no padding):")
print(padded[1, -5:])
