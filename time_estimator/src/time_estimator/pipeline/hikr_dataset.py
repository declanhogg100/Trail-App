import pandas as pd

from time_estimator.pipeline.parse_gpx import compute_grade, parse_gpx_string, resample_by_distance

# bounds scoped to single-day hikes -- multi-day treks are excluded, not just
# capped, because our distance/grade computation bridges across GPX track-segment
# boundaries, which fabricates large phantom distances across multi-day gaps
DISTANCE_RANGE_M = (200, 80_000)
ELEVATION_MAX_M = 10_000
MOVING_TIME_RANGE_S = (300, 16 * 3600)
# upper bound tightened from 20 to 6 km/h -- above ~6 km/h is realistically
# trail running, not hiking; the pace distribution shows a clear break there
# (95th percentile 6.1 km/h vs 97th percentile 9.3 km/h), consistent with a
# distinct running population mixed into the scraped hikr.org data
PACE_RANGE_KMH = (0.5, 6.0)

# distance buckets a user's pace gets conditioned on -- pace is not uniform
# across hike lengths (short hikes are brisker on average across the whole
# population), so a single blended per-user average pace systematically
# misrepresents a user's pace on hikes shorter/longer than what they usually do
DISTANCE_BUCKET_EDGES_M = [0, 3_000, 6_000, 10_000, 15_000, 22_000, 100_000]
DISTANCE_BUCKET_LABELS = ["<3km", "3-6km", "6-10km", "10-15km", "15-22km", "22km+"]


def load_hikr_csv(filepath: str) -> pd.DataFrame:
    df = pd.read_csv(filepath)
    df["start_time"] = pd.to_datetime(df["start_time"], errors="coerce")
    df["end_time"] = pd.to_datetime(df["end_time"], errors="coerce")
    return df


def filter_valid_hikes(df: pd.DataFrame, verbose: bool = True) -> pd.DataFrame:
    n_start = len(df)

    def report(label: str) -> None:
        if verbose:
            print(f"after {label}: {len(df)}")

    df = df[df["length_3d"].between(*DISTANCE_RANGE_M)]
    report("distance range filter")

    df = df[(df["uphill"] <= ELEVATION_MAX_M) & (df["downhill"] <= ELEVATION_MAX_M)]
    report("elevation range filter")

    df = df[df["moving_time"].between(*MOVING_TIME_RANGE_S)]
    report("moving_time range filter")

    df["pace_kmh"] = (df["length_3d"] / 1000) / (df["moving_time"] / 3600)
    df = df[df["pace_kmh"].between(*PACE_RANGE_KMH)]
    report("pace plausibility filter")

    has_both_times = df["start_time"].notna() & df["end_time"].notna()
    elapsed_s = (df["end_time"] - df["start_time"]).dt.total_seconds()
    df = df[~has_both_times | (df["moving_time"] <= elapsed_s)]
    report("start/end consistency filter")

    if verbose:
        print(f"final: {len(df)} / {n_start} rows kept ({len(df) / n_start:.1%})")

    return df


def build_segment_dataset(clean_df: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    segment_dfs = []
    failed_ids = []

    for _, row in clean_df.iterrows():
        try:
            points_df = parse_gpx_string(row["gpx"])
            resampled = compute_grade(resample_by_distance(points_df))
            if resampled.isna().any().any():
                raise ValueError("resampled segments contain NaN (partial missing elevation)")
            resampled["hike_id"] = row["_id"]
            segment_dfs.append(resampled)
        except Exception:
            failed_ids.append(row["_id"])

    segments_df = pd.concat(segment_dfs, ignore_index=True)
    return segments_df, failed_ids


def distance_bucket(length_3d: pd.Series) -> pd.Series:
    # cast off pandas' Categorical dtype immediately -- otherwise it silently
    # propagates through .map()/arithmetic later and breaks in confusing ways
    return pd.cut(length_3d, bins=DISTANCE_BUCKET_EDGES_M, labels=DISTANCE_BUCKET_LABELS).astype(str)


def fit_user_pace_stats(hikes_df: pd.DataFrame, train_ids) -> tuple[pd.Series, pd.Series, float]:
    train_hikes = hikes_df[hikes_df["hike_id"].isin(train_ids)].copy()
    global_mean_pace = train_hikes["pace_kmh"].mean()

    train_hikes["distance_bucket"] = distance_bucket(train_hikes["length_3d"])
    bucket_mean_pace = train_hikes.groupby("distance_bucket", observed=True)["pace_kmh"].mean()

    # how much faster/slower than average this user tends to be, independent
    # of distance -- assumed roughly consistent across hike lengths, so it can
    # be estimated from ALL of a user's hikes, even ones far from the distance
    # bucket being predicted for
    user_mean_pace = train_hikes.groupby("user")["pace_kmh"].mean()
    user_offset = user_mean_pace - global_mean_pace

    return bucket_mean_pace, user_offset, global_mean_pace
