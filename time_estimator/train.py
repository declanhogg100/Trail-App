import pickle
import time

import numpy as np
import pandas as pd
import torch
import torch.nn as nn

from time_estimator.model.gru import GRUTimeEstimator
from time_estimator.pipeline.dataset import (
    FEATURE_COLUMNS,
    collate_trails,
    fit_normalization_stats,
    group_segments_by_hike,
    normalize_features,
)
from time_estimator.pipeline.hikr_dataset import distance_bucket, fit_user_pace_stats

BATCH_SIZE = 32
NUM_EPOCHS = 20
VAL_FRACTION = 0.1
SEED = 0

hikes_df = pd.read_parquet("data/hikr/hikes.parquet")
segments_df = pd.read_parquet("data/hikr/segments.parquet")
segments_by_hike = group_segments_by_hike(segments_df)

rng = np.random.default_rng(SEED)
hike_ids = hikes_df["hike_id"].to_numpy()
rng.shuffle(hike_ids)
n_val = int(len(hike_ids) * VAL_FRACTION)
val_ids = hike_ids[:n_val]
train_ids = hike_ids[n_val:]
print(f"train hikes: {len(train_ids)}, val hikes: {len(val_ids)}")

# fit normalization on the training split only, then apply the same fixed
# transform to every hike (train and val) -- never re-fit per split
train_trail_dfs = [segments_by_hike[hid] for hid in train_ids]
feature_mean, feature_std = fit_normalization_stats(train_trail_dfs)

moving_time_by_id = hikes_df.set_index("hike_id")["moving_time"]

# train on log(moving_time) rather than raw seconds -- MSE on raw time is
# dominated by absolute error on long hikes (times span minutes to ~16h),
# which implicitly deprioritizes getting short hikes right; log-space
# differences correspond to relative error instead, weighting all hike
# lengths more evenly
log_moving_time_by_id = np.log(moving_time_by_id)
train_targets_raw = log_moving_time_by_id.loc[train_ids].to_numpy()
target_mean = train_targets_raw.mean()
target_std = train_targets_raw.std()

# per-user historical pace, conditioned on hike distance and fit on training
# hikes only: predicted pace = typical pace for hikes of this distance +
# how much faster/slower than average this user tends to be. Falls back
# gracefully for cold-start users (offset defaults to 0, i.e. assume average)
user_by_hike = hikes_df.set_index("hike_id")["user"]
bucket_by_hike = distance_bucket(hikes_df.set_index("hike_id")["length_3d"])
bucket_mean_pace, user_offset, global_mean_pace = fit_user_pace_stats(hikes_df, train_ids)


def get_raw_pace(ids_batch: np.ndarray) -> np.ndarray:
    buckets = bucket_by_hike.loc[ids_batch]
    baseline = buckets.map(bucket_mean_pace).fillna(global_mean_pace)
    users = user_by_hike.loc[ids_batch]
    offsets = users.map(user_offset).fillna(0.0)
    return (baseline + offsets).to_numpy()


train_raw_pace = get_raw_pace(train_ids)
user_pace_mean = train_raw_pace.mean()
user_pace_std = train_raw_pace.std()

# precompute normalized segment tables once, up front -- avoids redoing the
# same normalization arithmetic for every hike on every single epoch
normalized_by_hike = {
    hid: normalize_features(df, feature_mean, feature_std) for hid, df in segments_by_hike.items()
}


def get_batch(
    ids_batch: np.ndarray,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    trail_dfs = [normalized_by_hike[hid] for hid in ids_batch]
    padded, lengths = collate_trails(trail_dfs)

    raw_targets = log_moving_time_by_id.loc[ids_batch].to_numpy()
    targets = torch.tensor((raw_targets - target_mean) / target_std, dtype=torch.float32)

    raw_pace = get_raw_pace(ids_batch)
    normalized_pace = (raw_pace - user_pace_mean) / user_pace_std
    user_features = torch.tensor(normalized_pace, dtype=torch.float32).unsqueeze(1)

    return padded, lengths, user_features, targets


model = GRUTimeEstimator(num_features=len(FEATURE_COLUMNS))
loss_fn = nn.MSELoss()
optimizer = torch.optim.Adam(model.parameters(), lr=0.01)
scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="min", factor=0.5, patience=2)

for epoch in range(NUM_EPOCHS):
    epoch_start = time.time()

    model.train()
    perm = rng.permutation(len(train_ids))
    train_loss_total = 0.0
    n_batches = 0
    for start in range(0, len(train_ids), BATCH_SIZE):
        batch_ids = train_ids[perm[start : start + BATCH_SIZE]]
        padded, lengths, user_features, targets = get_batch(batch_ids)

        optimizer.zero_grad()
        predictions = model(padded, lengths, user_features)
        loss = loss_fn(predictions, targets)
        loss.backward()
        optimizer.step()

        train_loss_total += loss.item()
        n_batches += 1

    model.eval()
    abs_errors_minutes = []
    with torch.no_grad():
        for start in range(0, len(val_ids), BATCH_SIZE):
            batch_ids = val_ids[start : start + BATCH_SIZE]
            padded, lengths, user_features, targets = get_batch(batch_ids)
            predictions = model(padded, lengths, user_features)
            pred_log = predictions.numpy() * target_std + target_mean
            pred_seconds = np.exp(pred_log)
            true_seconds = moving_time_by_id.loc[batch_ids].to_numpy()
            abs_errors_minutes.extend(np.abs(pred_seconds - true_seconds) / 60)

    val_mae = np.mean(abs_errors_minutes)
    scheduler.step(val_mae)

    elapsed = time.time() - epoch_start
    current_lr = optimizer.param_groups[0]["lr"]
    print(
        f"epoch {epoch}: train_loss={train_loss_total / n_batches:.4f}, "
        f"val_MAE={val_mae:.1f} min, lr={current_lr:.5f} ({elapsed:.1f}s)"
    )

torch.save(model.state_dict(), "data/hikr/gru_time_estimator.pt")

# everything inference needs beyond the model weights themselves -- none of
# this was persisted before, so a fresh process had no way to reproduce the
# exact normalization the model was trained under
inference_stats = {
    "feature_mean": feature_mean,
    "feature_std": feature_std,
    "target_mean": target_mean,
    "target_std": target_std,
    "user_pace_mean": user_pace_mean,
    "user_pace_std": user_pace_std,
    "bucket_mean_pace": bucket_mean_pace,
    "global_mean_pace": global_mean_pace,
}
with open("data/hikr/inference_stats.pkl", "wb") as f:
    pickle.dump(inference_stats, f)

print("---")
print("saved model to data/hikr/gru_time_estimator.pt")
print("saved inference stats to data/hikr/inference_stats.pkl")
