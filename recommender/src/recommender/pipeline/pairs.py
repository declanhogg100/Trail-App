import numpy as np
import pandas as pd

# distance_m and elevation_gain_m are heavily right-skewed (a handful of
# multi-day trails are 100-1000x longer than the median), so they're
# log-transformed before standardizing -- otherwise those few outliers would
# dominate the numeric comparisons and drown out every other feature
LOG_FEATURES = ["distance_m", "elevation_gain_m"]

LINEAR_FEATURES = [
    "grade_std",
    "peak_elevation_m",
    "peak_prominence_m",
    "low_elevation_m",
    "low_relative_m",
    "tree_cover_pct",
]

# a positive pair requires EVERY numeric feature to independently be within
# this many standard deviations -- an AND across features, not a summed
# Euclidean distance. That's the point: a Euclidean sum lets one feature be
# very different as long as others compensate by being very close, while
# this rule can't be satisfied that way. It's a rule a linear/Euclidean
# metric on these features literally cannot reproduce, so there's an actual
# nonlinear pattern for the network to learn instead of just re-deriving
# Euclidean distance on its own input.
NUMERIC_CLOSE_THRESHOLD = 1.0
N_POSITIVES = 3
N_NEGATIVES = 3
# negatives are drawn from the trails CLOSEST to the anchor by raw Euclidean
# distance that still fail the gated positive rule -- these are the cases a
# linear/Euclidean metric would call "similar" but the gate says aren't, so
# they're the only negatives that actually test whether the network learned
# the nonlinear rule rather than just Euclidean distance on its own input
HARD_NEGATIVE_POOL_FRACTION = 0.1


ALL_BIOME_COLUMNS = [
    "biome_Deserts & Xeric Shrublands",
    "biome_Mediterranean Forests, Woodlands & Scrub",
    "biome_Montane Grasslands & Shrublands",
    "biome_Temperate Broadleaf & Mixed Forests",
    "biome_Temperate Conifer Forests",
    "biome_Tropical & Subtropical Coniferous Forests",
    "biome_Tropical & Subtropical Grasslands, Savannas & Shrublands",
    "biome_Tropical & Subtropical Moist Broadleaf Forests",
    "biome_Tundra",
]


def fit_feature_stats(df: pd.DataFrame) -> dict:
    # fit *only* on the trails passed in (e.g. the train split) -- the
    # resulting mean/std are then reused to transform any other split, so no
    # information about the validation trails leaks into normalization
    numeric = pd.DataFrame(index=df.index)
    for col in LOG_FEATURES:
        numeric[col] = np.log1p(df[col])
    for col in LINEAR_FEATURES:
        numeric[col] = df[col]

    return {
        "means": numeric.mean(),
        "stds": numeric.std().replace(0, 1.0),
        "numeric_columns": LOG_FEATURES + LINEAR_FEATURES,
        "biome_columns": ALL_BIOME_COLUMNS,
    }


def standardize_numeric(df: pd.DataFrame, stats: dict) -> np.ndarray:
    numeric = pd.DataFrame(index=df.index)
    for col in LOG_FEATURES:
        numeric[col] = np.log1p(df[col])
    for col in LINEAR_FEATURES:
        numeric[col] = df[col]
    return ((numeric - stats["means"]) / stats["stds"]).to_numpy()


def transform_features(df: pd.DataFrame, stats: dict) -> np.ndarray:
    # the network's input representation: standardized numeric features plus
    # one-hot biome, concatenated into one vector. This is deliberately kept
    # separate from the *heuristic* below, which treats biome as a hard gate
    # rather than as more dimensions in the same vector.
    standardized = standardize_numeric(df, stats)

    biome_dummies = pd.get_dummies(df["biome_name"], prefix="biome").astype(float)
    # reindex against the full known biome set (fixed at fit time) so a split
    # missing a rare biome still produces a column of zeros for it, rather
    # than shifting every other column's position
    biome_dummies = biome_dummies.reindex(columns=stats["biome_columns"], fill_value=0.0)

    return np.concatenate([standardized, biome_dummies.to_numpy()], axis=1)


def generate_triplets(
    df: pd.DataFrame,
    numeric_matrix: np.ndarray,
    n_positives: int = N_POSITIVES,
    n_negatives: int = N_NEGATIVES,
    close_threshold: float = NUMERIC_CLOSE_THRESHOLD,
    hard_negative_pool_fraction: float = HARD_NEGATIVE_POOL_FRACTION,
    seed: int = 42,
) -> pd.DataFrame:
    # df and numeric_matrix must be row-aligned (same order, 0..n-1 index) --
    # pass a matrix restricted to a specific split (train-only or val-only)
    # to keep each split's heuristic pairs from leaking across the other
    n = len(df)
    rng = np.random.default_rng(seed)
    osm_ids = df["osm_id"].to_numpy()
    biome = df["biome_name"].to_numpy()
    pool_size = max(1, int(n * hard_negative_pool_fraction))

    rows = []
    for i in range(n):
        diffs = np.abs(numeric_matrix - numeric_matrix[i])  # (n, num_numeric_features)

        close_on_every_feature = (diffs <= close_threshold).all(axis=1)
        same_biome = biome == biome[i]
        positive_mask = close_on_every_feature & same_biome
        positive_mask[i] = False
        positive_candidates = np.where(positive_mask)[0]
        if len(positive_candidates) == 0:
            continue  # no trail satisfies the gated rule for this anchor -- skip it

        euclidean_dist = np.linalg.norm(numeric_matrix - numeric_matrix[i], axis=1)
        nearest_by_euclidean = np.argsort(euclidean_dist)[: pool_size + 1]
        nearest_by_euclidean = nearest_by_euclidean[nearest_by_euclidean != i]
        negative_candidates = nearest_by_euclidean[~positive_mask[nearest_by_euclidean]]

        chosen_positives = rng.choice(
            positive_candidates, size=min(n_positives, len(positive_candidates)), replace=False
        )
        chosen_negatives = rng.choice(
            negative_candidates, size=min(n_negatives, len(negative_candidates)), replace=False
        )

        for pos_idx in chosen_positives:
            for neg_idx in chosen_negatives:
                rows.append(
                    {
                        "anchor_osm_id": osm_ids[i],
                        "positive_osm_id": osm_ids[pos_idx],
                        "negative_osm_id": osm_ids[neg_idx],
                    }
                )

    return pd.DataFrame(rows)
