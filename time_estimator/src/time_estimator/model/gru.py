import torch
import torch.nn as nn
from torch.nn.utils.rnn import pack_padded_sequence


class GRUTimeEstimator(nn.Module):
    def __init__(self, num_features: int, hidden_dim: int = 32):
        super().__init__()
        self.gru = nn.GRU(input_size=num_features, hidden_size=hidden_dim, batch_first=True)
        self.fc = nn.Linear(hidden_dim, 1)

    def forward(self, padded_batch: torch.Tensor, lengths: torch.Tensor) -> torch.Tensor:
        packed = pack_padded_sequence(
            padded_batch, lengths, batch_first=True, enforce_sorted=False
        )
        _, hidden = self.gru(packed)
        last_layer_hidden = hidden[-1]
        return self.fc(last_layer_hidden).squeeze(-1)
