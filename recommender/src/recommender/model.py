import torch
from torch import nn


class WeightedDistanceEncoder(nn.Module):
    # learns one scalar weight per input feature and applies it before a
    # plain L2 distance -- a diagonal Mahalanobis metric, not a deep
    # network. Far fewer parameters than an MLP (one per feature, not per
    # connection), much harder to overfit on a small dataset, and every
    # learned weight is directly interpretable as "how much this feature
    # matters for similarity."
    def __init__(self, input_dim: int):
        super().__init__()
        # parameterized in log-space so exp() always yields a positive
        # weight, regardless of what direction gradient descent pushes it
        self.log_weights = nn.Parameter(torch.zeros(input_dim))

    def weights(self) -> torch.Tensor:
        return torch.exp(self.log_weights)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # scaling feature i by sqrt(weight_i) before a plain L2 distance is
        # equivalent to weighting that feature's *squared* difference by
        # weight_i in the underlying distance calculation. weights start at
        # 1 (log_weight=0), so at initialization this is identical to the
        # unweighted standardized-Euclidean baseline.
        return x * torch.sqrt(self.weights())
