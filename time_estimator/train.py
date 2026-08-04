import torch
import torch.nn as nn

from time_estimator.model.gru import GRUTimeEstimator
from time_estimator.pipeline.dataset import (
    FEATURE_COLUMNS,
    collate_trails,
    fit_normalization_stats,
    normalize_features,
)
from time_estimator.pipeline.parse_gpx import compute_grade, load_gpx_points, resample_by_distance

df = load_gpx_points("data/raw/Mojstrovka.gpx")
resampled = compute_grade(resample_by_distance(df, step_m=40.0))

# two non-overlapping slices, not a prefix relationship -- a shared prefix
# between "trails" is pathologically hard for an RNN to tell apart early in
# training, which isn't representative of two genuinely different real trails
first_half = resampled.iloc[:35].reset_index(drop=True)
second_half = resampled.iloc[35:].reset_index(drop=True)

# fit normalization stats once (would be the training set, in a real dataset),
# then apply the same fixed transform to every trail -- never re-fit per trail
mean, std = fit_normalization_stats([first_half, second_half])
first_half = normalize_features(first_half, mean, std)
second_half = normalize_features(second_half, mean, std)

padded, lengths = collate_trails([first_half, second_half])

# no real labels yet -- fake target "minutes to complete" values, purely to verify
# the training loop is wired correctly (forward -> loss -> backward -> update)
targets = torch.tensor([45.0, 90.0])

model = GRUTimeEstimator(num_features=len(FEATURE_COLUMNS))
loss_fn = nn.MSELoss()
optimizer = torch.optim.Adam(model.parameters(), lr=0.01)

for epoch in range(1000):
    optimizer.zero_grad()
    predictions = model(padded, lengths)
    loss = loss_fn(predictions, targets)
    loss.backward()
    optimizer.step()

    if epoch % 100 == 0:
        print(f"epoch {epoch}: loss={loss.item():.4f}, predictions={predictions.detach()}")

print("---")
print(f"final predictions: {model(padded, lengths)}")
print(f"targets: {targets}")
