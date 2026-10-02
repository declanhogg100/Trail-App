import pickle
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from recommender.model import WeightedDistanceEncoder
from recommender.pipeline.pairs import transform_features

EARTH_RADIUS_KM = 6371.0


def _haversine_km(lat1: float, lon1: float, lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
    # great-circle distance from one point to an array of points, vectorized
    # over the whole catalog at once rather than looped per trail
    lat1_r, lon1_r = np.radians(lat1), np.radians(lon1)
    lat2_r, lon2_r = np.radians(lat2), np.radians(lon2)
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1_r) * np.cos(lat2_r) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))

# resolved from this file's location, not the process's working directory --
# lets a server process started from anywhere (e.g. a combined API project)
# still find this project's data without relying on its launch directory
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
FEATURES_PATH = _PROJECT_ROOT / "data" / "trail_features.parquet"
MODEL_PATH = _PROJECT_ROOT / "data" / "trail_encoder.pt"
STATS_PATH = _PROJECT_ROOT / "data" / "feature_stats.pkl"


class TrailRecommender:
    def __init__(
        self,
        features_path: str | Path = FEATURES_PATH,
        model_path: str | Path = MODEL_PATH,
        stats_path: str | Path = STATS_PATH,
    ):
        self.trails = pd.read_parquet(features_path)

        with open(stats_path, "rb") as f:
            self.stats = pickle.load(f)

        # stats were fit on the training split only, at training time -- reused
        # here as-is (never refit) so every trail is standardized on the exact
        # same scale the model's learned weights were calibrated against
        matrix = transform_features(self.trails, self.stats)

        model = WeightedDistanceEncoder(input_dim=matrix.shape[1])
        model.load_state_dict(torch.load(model_path, weights_only=True))
        model.eval()

        # the whole catalog's embeddings are computed once, up front -- a
        # request only ever needs to compare against this fixed table, never
        # recompute it
        with torch.no_grad():
            self.embeddings = model(torch.tensor(matrix, dtype=torch.float32)).numpy()

        self.osm_id_to_row = {osm_id: i for i, osm_id in enumerate(self.trails["osm_id"])}

    def _to_summary(self, row: pd.Series) -> dict:
        return {
            "osm_id": int(row["osm_id"]),
            "name": row["name"],
            "distance_m": float(row["distance_m"]),
            "is_loop": bool(row["is_loop"]),
            "elevation_gain_m": float(row["elevation_gain_m"]),
            "biome_name": row["biome_name"],
        }

    def list_trails(self, search: str | None = None, limit: int = 50, offset: int = 0) -> dict:
        trails = self.trails
        if search:
            trails = trails[trails["name"].str.contains(search, case=False, na=False)]

        total = len(trails)
        page = trails.iloc[offset : offset + limit]
        return {"total": total, "trails": [self._to_summary(row) for _, row in page.iterrows()]}

    def near(self, lat: float, lon: float, radius_km: float = 50.0, limit: int = 20) -> list[dict]:
        dists = _haversine_km(lat, lon, self.trails["lat"].to_numpy(), self.trails["lon"].to_numpy())

        within_radius = np.where(dists <= radius_km)[0]
        order = within_radius[np.argsort(dists[within_radius])][:limit]

        results = []
        for idx in order:
            row = self.trails.iloc[idx]
            results.append({**self._to_summary(row), "distance_km": float(dists[idx])})
        return results

    def get_trail(self, osm_id: int) -> dict | None:
        if osm_id not in self.osm_id_to_row:
            return None
        row = self.trails.iloc[self.osm_id_to_row[osm_id]]
        return {
            **self._to_summary(row),
            "grade_std": float(row["grade_std"]),
            "peak_elevation_m": float(row["peak_elevation_m"]),
            "peak_prominence_m": float(row["peak_prominence_m"]),
            "low_elevation_m": float(row["low_elevation_m"]),
            "low_relative_m": float(row["low_relative_m"]),
            "tree_cover_pct": float(row["tree_cover_pct"]),
            "eco_name": row["eco_name"],
            "realm": row["realm"],
        }

    def recommend(self, liked_osm_ids: list[int], top_k: int = 10) -> list[dict]:
        liked_osm_ids = [osm_id for osm_id in liked_osm_ids if osm_id in self.osm_id_to_row]
        if not liked_osm_ids:
            raise ValueError("none of the provided liked_osm_ids were found in the trail catalog")

        liked_rows = [self.osm_id_to_row[osm_id] for osm_id in liked_osm_ids]
        liked_embeddings = self.embeddings[liked_rows]  # (num_liked, embed_dim)

        # distance from every trail in the catalog to every liked trail
        diffs = self.embeddings[:, None, :] - liked_embeddings[None, :, :]
        dists = np.linalg.norm(diffs, axis=2)  # (n_catalog, num_liked)

        # a candidate only needs to resemble ONE liked trail to be a good
        # recommendation -- averaging embeddings instead would collapse a
        # varied taste profile (e.g. likes both alpine and desert hikes) into
        # a bland midpoint that resembles neither
        min_dist = dists.min(axis=1)
        closest_liked_idx = dists.argmin(axis=1)

        candidate_mask = np.ones(len(self.trails), dtype=bool)
        candidate_mask[liked_rows] = False  # never recommend something already liked

        order = np.argsort(min_dist)
        order = order[candidate_mask[order]][:top_k]

        results = []
        for idx in order:
            row = self.trails.iloc[idx]
            results.append(
                {
                    "osm_id": int(row["osm_id"]),
                    "name": row["name"],
                    "distance_m": float(row["distance_m"]),
                    "is_loop": bool(row["is_loop"]),
                    "elevation_gain_m": float(row["elevation_gain_m"]),
                    "biome_name": row["biome_name"],
                    "similarity_score": float(min_dist[idx]),
                    "because_you_liked_osm_id": int(liked_osm_ids[closest_liked_idx[idx]]),
                }
            )
        return results
