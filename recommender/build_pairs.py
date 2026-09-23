import pandas as pd

from recommender.pipeline.pairs import fit_feature_stats, generate_triplets, standardize_numeric

df = pd.read_parquet("data/trail_features.parquet")
print(f"trails: {len(df)}")

stats = fit_feature_stats(df)
numeric_matrix = standardize_numeric(df, stats)
triplets = generate_triplets(df, numeric_matrix)
print(f"triplets: {len(triplets)}")

triplets.to_parquet("data/trail_triplets.parquet", index=False)
print("saved to data/trail_triplets.parquet")
