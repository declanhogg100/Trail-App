import pickle

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset

from recommender.model import WeightedDistanceEncoder
from recommender.pipeline.pairs import (
    fit_feature_stats,
    generate_triplets,
    standardize_numeric,
    transform_features,
)

SEED = 42
VAL_FRACTION = 0.15
BATCH_SIZE = 64
EPOCHS = 100
LR = 1e-2
MARGIN = 0.3
WEIGHT_DECAY = 1e-4

df = pd.read_parquet("data/trail_features.parquet")

# split at the trail level, *before* generating triplets -- each split then
# gets its own heuristic triplets (nearest/farthest neighbors computed only
# within that split), so no validation trail's identity ever appears in a
# training triplet
rng = np.random.default_rng(SEED)
shuffled = rng.permutation(len(df))
n_val = int(len(df) * VAL_FRACTION)
val_df = df.iloc[shuffled[:n_val]].reset_index(drop=True)
train_df = df.iloc[shuffled[n_val:]].reset_index(drop=True)
print(f"train trails: {len(train_df)}, val trails: {len(val_df)}")

# normalization stats (mean/std per feature) are fit on train only, then
# applied to val -- val never influences how features are scaled
stats = fit_feature_stats(train_df)
# the network's input: standardized numeric features + one-hot biome, combined
train_matrix = transform_features(train_df, stats)
val_matrix = transform_features(val_df, stats)

# the heuristic labels: gated rule over standardized numeric features and
# biome treated separately (not folded into one Euclidean vector)
train_numeric = standardize_numeric(train_df, stats)
val_numeric = standardize_numeric(val_df, stats)

train_triplets = generate_triplets(train_df, train_numeric, seed=SEED)
val_triplets = generate_triplets(val_df, val_numeric, seed=SEED)
print(f"train triplets: {len(train_triplets)}, val triplets: {len(val_triplets)}")

train_features_t = torch.tensor(train_matrix, dtype=torch.float32)
val_features_t = torch.tensor(val_matrix, dtype=torch.float32)


class TripletDataset(Dataset):
    def __init__(self, triplets_df: pd.DataFrame, osm_to_idx: dict):
        self.anchor_idx = triplets_df["anchor_osm_id"].map(osm_to_idx).to_numpy()
        self.positive_idx = triplets_df["positive_osm_id"].map(osm_to_idx).to_numpy()
        self.negative_idx = triplets_df["negative_osm_id"].map(osm_to_idx).to_numpy()

    def __len__(self) -> int:
        return len(self.anchor_idx)

    def __getitem__(self, i: int):
        return self.anchor_idx[i], self.positive_idx[i], self.negative_idx[i]


train_osm_to_idx = {osm_id: i for i, osm_id in enumerate(train_df["osm_id"])}
val_osm_to_idx = {osm_id: i for i, osm_id in enumerate(val_df["osm_id"])}

train_dataset = TripletDataset(train_triplets, train_osm_to_idx)
val_dataset = TripletDataset(val_triplets, val_osm_to_idx)
train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True)

model = WeightedDistanceEncoder(input_dim=train_matrix.shape[1])
optimizer = torch.optim.Adam(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
loss_fn = nn.TripletMarginLoss(margin=MARGIN)

# raw-Euclidean-distance baseline (no network at all) on the same val
# triplets -- the network only proves it learned something if it beats this
baseline_d_pos = np.linalg.norm(
    val_matrix[val_dataset.anchor_idx] - val_matrix[val_dataset.positive_idx], axis=1
)
baseline_d_neg = np.linalg.norm(
    val_matrix[val_dataset.anchor_idx] - val_matrix[val_dataset.negative_idx], axis=1
)
baseline_val_acc = (baseline_d_pos < baseline_d_neg).mean()
print(f"untrained raw-Euclidean baseline val_acc: {baseline_val_acc:.3f}")


def triplet_accuracy(features_t: torch.Tensor, dataset: TripletDataset) -> float:
    model.eval()
    with torch.no_grad():
        embeddings = model(features_t)
        anchor = embeddings[dataset.anchor_idx]
        positive = embeddings[dataset.positive_idx]
        negative = embeddings[dataset.negative_idx]
        d_pos = (anchor - positive).pow(2).sum(-1)
        d_neg = (anchor - negative).pow(2).sum(-1)
        accuracy = (d_pos < d_neg).float().mean().item()
    model.train()
    return accuracy


best_val_acc = -1.0
best_state = None
best_epoch = -1

for epoch in range(1, EPOCHS + 1):
    total_loss = 0.0
    for anchor_idx, positive_idx, negative_idx in train_loader:
        anchor = model(train_features_t[anchor_idx])
        positive = model(train_features_t[positive_idx])
        negative = model(train_features_t[negative_idx])
        loss = loss_fn(anchor, positive, negative)

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        total_loss += loss.item() * len(anchor_idx)

    train_loss = total_loss / len(train_dataset)
    val_acc = triplet_accuracy(val_features_t, val_dataset)

    if val_acc > best_val_acc:
        best_val_acc = val_acc
        best_state = {k: v.clone() for k, v in model.state_dict().items()}
        best_epoch = epoch

    if epoch % 10 == 0 or epoch == 1:
        train_acc = triplet_accuracy(train_features_t, train_dataset)
        print(
            f"epoch {epoch:3d}  train_loss={train_loss:.4f}  "
            f"train_acc={train_acc:.3f}  val_acc={val_acc:.3f}"
        )

print(f"best val_acc={best_val_acc:.3f} at epoch {best_epoch} (baseline={baseline_val_acc:.3f})")

model.load_state_dict(best_state)
feature_names = stats["numeric_columns"] + stats["biome_columns"]
learned_weights = model.weights().detach().numpy()
print("\nlearned feature weights (1.0 = baseline, untouched):")
for name, weight in sorted(zip(feature_names, learned_weights), key=lambda p: -p[1]):
    print(f"  {name:55s} {weight:.3f}")

torch.save(best_state, "data/trail_encoder.pt")
with open("data/feature_stats.pkl", "wb") as f:
    pickle.dump(stats, f)
print("saved model to data/trail_encoder.pt and stats to data/feature_stats.pkl")
