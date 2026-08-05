import torch
import torch.nn as nn
from torch.nn.utils.rnn import pack_padded_sequence


class GRUTimeEstimator(nn.Module):
    def __init__(self, num_features: int, hidden_dim: int = 32, num_user_features: int = 1):
        super().__init__()
        self.gru = nn.GRU(input_size=num_features, hidden_size=hidden_dim, batch_first=True)
        self.fc = nn.Linear(hidden_dim + num_user_features, 1)

    def forward(
        self, padded_batch: torch.Tensor, lengths: torch.Tensor, user_features: torch.Tensor
    ) -> torch.Tensor:
        packed = pack_padded_sequence(
            padded_batch, lengths, batch_first=True, enforce_sorted=False
        )
        _, hidden = self.gru(packed)
        last_layer_hidden = hidden[-1]
        combined = torch.cat([last_layer_hidden, user_features], dim=1)
        return self.fc(combined).squeeze(-1)
