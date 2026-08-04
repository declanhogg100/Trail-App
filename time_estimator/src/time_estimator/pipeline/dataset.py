import pandas as pd
import torch
from torch.nn.utils.rnn import pad_sequence

FEATURE_COLUMNS = ["elevation", "grade"]


def fit_normalization_stats(trail_dfs: list[pd.DataFrame]) -> tuple[pd.Series, pd.Series]:
    combined = pd.concat(trail_dfs)[FEATURE_COLUMNS]
    return combined.mean(), combined.std()


def normalize_features(df: pd.DataFrame, mean: pd.Series, std: pd.Series) -> pd.DataFrame:
    df = df.copy()
    df[FEATURE_COLUMNS] = (df[FEATURE_COLUMNS] - mean) / std
    return df


def trail_to_tensor(df: pd.DataFrame) -> torch.Tensor:
    return torch.tensor(df[FEATURE_COLUMNS].values, dtype=torch.float32)


def collate_trails(trail_dfs: list[pd.DataFrame]) -> tuple[torch.Tensor, torch.Tensor]:
    tensors = [trail_to_tensor(df) for df in trail_dfs]
    lengths = torch.tensor([len(t) for t in tensors])
    padded = pad_sequence(tensors, batch_first=True)
    return padded, lengths
