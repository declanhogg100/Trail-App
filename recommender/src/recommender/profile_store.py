from pathlib import Path

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILES_PATH = _PROJECT_ROOT / "data" / "trail_elevation_profiles.parquet"


class TrailProfileStore:
    def __init__(self, profiles_path: str | Path = PROFILES_PATH):
        self.profiles = pd.read_parquet(profiles_path)
        self._osm_id_to_row = {osm_id: i for i, osm_id in enumerate(self.profiles["osm_id"])}

    def get_profile(self, osm_id: int) -> pd.DataFrame | None:
        if osm_id not in self._osm_id_to_row:
            return None
        row = self.profiles.iloc[self._osm_id_to_row[osm_id]]
        distance_m = np.asarray(row["distance_m"], dtype=float)
        elevation = np.asarray(row["elevation"], dtype=float)

        # grade here is rise-over-run with `run` taken directly from
        # distance_m, since that column is already pure horizontal geodesic
        # distance (see resample_elevation_profile) -- unlike a GPX's 3D
        # distance, there's no hypotenuse to correct for
        rise = np.diff(elevation, prepend=elevation[0])
        run = np.diff(distance_m, prepend=distance_m[0])
        with np.errstate(divide="ignore", invalid="ignore"):
            grade = np.where(run > 0, rise / run, 0.0)

        return pd.DataFrame({"distance_m": distance_m, "elevation": elevation, "grade": grade})
