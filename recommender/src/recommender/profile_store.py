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


def build_round_trip_profile(profile: pd.DataFrame) -> pd.DataFrame:
    # an out-and-back trail's real hike is the stored one-way profile
    # followed by the same path walked backwards -- mirror every point
    # except the turnaround itself (already the one-way profile's last
    # point) so distance keeps climbing continuously instead of resetting
    distance_m = profile["distance_m"].to_numpy()
    elevation = profile["elevation"].to_numpy()
    total_m = distance_m[-1]

    return_distance_m = total_m + (total_m - distance_m[-2::-1])
    return_elevation = elevation[-2::-1]

    round_trip_distance_m = np.concatenate([distance_m, return_distance_m])
    round_trip_elevation = np.concatenate([elevation, return_elevation])

    rise = np.diff(round_trip_elevation, prepend=round_trip_elevation[0])
    run = np.diff(round_trip_distance_m, prepend=round_trip_distance_m[0])
    with np.errstate(divide="ignore", invalid="ignore"):
        grade = np.where(run > 0, rise / run, 0.0)

    return pd.DataFrame(
        {"distance_m": round_trip_distance_m, "elevation": round_trip_elevation, "grade": grade}
    )
