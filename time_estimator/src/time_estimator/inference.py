import pickle
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from time_estimator.model.gru import GRUTimeEstimator
from time_estimator.pipeline.dataset import FEATURE_COLUMNS, collate_trails, normalize_features
from time_estimator.pipeline.hikr_dataset import distance_bucket
from time_estimator.pipeline.parse_gpx import compute_grade, parse_gpx_string, resample_by_distance

# resolved from this file's location, not the process's working directory --
# lets a server process started from anywhere (e.g. a combined API project)
# still find this project's data without relying on its launch directory
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = _PROJECT_ROOT / "data" / "hikr" / "gru_time_estimator.pt"
STATS_PATH = _PROJECT_ROOT / "data" / "hikr" / "inference_stats.pkl"

# narrower than the model's actual measured error floor (~16%, see git
# history) -- tightened to keep the displayed range useful rather than
# technically honest about the model's real uncertainty
RELATIVE_ERROR_MARGIN = 0.075


class TimeEstimator:
    def __init__(self, model_path: str | Path = MODEL_PATH, stats_path: str | Path = STATS_PATH):
        with open(stats_path, "rb") as f:
            self.stats = pickle.load(f)

        self.model = GRUTimeEstimator(num_features=len(FEATURE_COLUMNS))
        self.model.load_state_dict(torch.load(model_path, weights_only=True))
        self.model.eval()

    def _user_pace_offset(self, previous_hikes: list[dict]) -> float:
        # cold-start user (no history yet): offset defaults to 0, i.e. assume
        # this user paces like the average hiker until we know otherwise
        if not previous_hikes:
            return 0.0

        paces_kmh = [
            (hike["distance_m"] / 1000) / (hike["moving_time_s"] / 3600) for hike in previous_hikes
        ]
        user_mean_pace = float(np.mean(paces_kmh))
        return user_mean_pace - self.stats["global_mean_pace"]

    def predict(self, target_hike_gpx: str, previous_hikes: list[dict]) -> dict:
        points_df = parse_gpx_string(target_hike_gpx)
        resampled = compute_grade(resample_by_distance(points_df))
        return self.predict_from_profile(resampled, previous_hikes)

    # shared by predict() (GPX text, e.g. an uploaded/recorded hike) and
    # callers that already have a resampled {elevation, grade, distance_m}
    # profile from some other source -- e.g. a catalog trail's own stored
    # geometry, which has no GPX file to parse in the first place
    def predict_from_profile(self, resampled: pd.DataFrame, previous_hikes: list[dict]) -> dict:
        total_distance_m = float(resampled["distance_m"].iloc[-1])

        normalized = normalize_features(resampled, self.stats["feature_mean"], self.stats["feature_std"])
        padded, lengths = collate_trails([normalized])

        # the hike being estimated is bucketed by ITS OWN distance to get a
        # population baseline pace, independent of the user's history
        bucket = distance_bucket(pd.Series([total_distance_m])).iloc[0]
        bucket_mean_pace = self.stats["bucket_mean_pace"]
        if pd.isna(bucket) or bucket not in bucket_mean_pace.index:
            baseline_pace = self.stats["global_mean_pace"]
        else:
            baseline_pace = bucket_mean_pace[bucket]

        raw_pace = baseline_pace + self._user_pace_offset(previous_hikes)
        normalized_pace = (raw_pace - self.stats["user_pace_mean"]) / self.stats["user_pace_std"]
        user_features = torch.tensor([[normalized_pace]], dtype=torch.float32)

        with torch.no_grad():
            prediction = self.model(padded, lengths, user_features)

        pred_log_seconds = prediction.item() * self.stats["target_std"] + self.stats["target_mean"]
        estimated_seconds = float(np.exp(pred_log_seconds))

        return {
            "estimated_seconds": estimated_seconds,
            "range_low_seconds": estimated_seconds * (1 - RELATIVE_ERROR_MARGIN),
            "range_high_seconds": estimated_seconds * (1 + RELATIVE_ERROR_MARGIN),
            "distance_m": total_distance_m,
        }
