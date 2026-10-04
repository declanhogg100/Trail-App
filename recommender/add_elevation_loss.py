import numpy as np
import pandas as pd

# pure array math over the already-built per-trail elevation profiles -- no
# DEM access and no model retraining needed. elevation_gain_m (in
# trail_features.parquet) is a real input feature to the trained similarity
# model, so it's left untouched; elevation_loss_m is purely additive and only
# used for display math (round-trip elevation gain = one-way gain + one-way
# loss, since a reversed path's climbs are exactly where the outbound path
# descended).
FEATURES_PATH = "data/trail_features.parquet"
PROFILES_PATH = "data/trail_elevation_profiles.parquet"


def compute_loss_m(elevation: list[float]) -> float:
    rise = np.diff(np.asarray(elevation, dtype=float))
    return float(-rise[rise < 0].sum())


if __name__ == "__main__":
    features = pd.read_parquet(FEATURES_PATH)
    profiles = pd.read_parquet(PROFILES_PATH)

    losses = profiles.assign(elevation_loss_m=profiles["elevation"].map(compute_loss_m))
    losses = losses[["osm_id", "elevation_loss_m"]]

    before = len(features)
    features = features.merge(losses, on="osm_id", how="left")
    missing = features["elevation_loss_m"].isna().sum()
    if missing:
        # a trail present in trail_features.parquet but missing from
        # trail_elevation_profiles.parquet (e.g. it failed to resample when
        # that file was built) -- fall back to treating it as a simple
        # there-and-back of its own gain, same as the old (wrong but
        # previously shipped) behavior, rather than leaving a NaN that'd
        # break every round-trip display for that one trail
        print(f"warning: {missing} trails have no elevation profile, falling back to gain as loss")
        features["elevation_loss_m"] = features["elevation_loss_m"].fillna(features["elevation_gain_m"])
    assert len(features) == before, "merge changed row count"

    features.to_parquet(FEATURES_PATH, index=False)
    print(f"added elevation_loss_m to {len(features)} trails ({missing} used the fallback)")
