from time_estimator.model.gru import GRUTimeEstimator
from time_estimator.pipeline.dataset import FEATURE_COLUMNS, collate_trails
from time_estimator.pipeline.parse_gpx import compute_grade, load_gpx_points, resample_by_distance

df = load_gpx_points("data/raw/Mojstrovka.gpx")
resampled = compute_grade(resample_by_distance(df, step_m=40.0))

short_trail = resampled.iloc[:40].reset_index(drop=True)
long_trail = resampled

padded, lengths = collate_trails([short_trail, long_trail])

model = GRUTimeEstimator(num_features=len(FEATURE_COLUMNS))
predictions = model(padded, lengths)

print(f"padded batch shape: {padded.shape}")
print(f"lengths: {lengths}")
print(f"predictions shape: {predictions.shape}")
print(f"predictions: {predictions}")
